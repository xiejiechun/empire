"""Seven actual registered contracts: source → Redis → shared archiver → query."""
import copy
import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.datasets.intraday import identity
from empire.plugins.datasets.kaipanla_products import ProductDataset
from tests.prefetch_source import prefetch_http
from tests.test_kaipanla_products import business_row


async def test_listing_supplement_source_to_query_pending_and_later_listed(monkeypatch):
    from tests.test_kaipanla_products import source
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    store = None
    newly_listed = False
    calls = []
    tomorrow = (datetime.now(CHINA).date() + timedelta(days=1)).isoformat()
    stocks = [dict(code=code, market=market, name='样本') for code, market in
              [('001381', 'SZ'), ('000001', 'SZ'), ('689009', 'SH'), ('920157', 'BJ')]]
    try:
        await manager.start('collector.kaipanla_quote')
        c = manager.registry.get('collector.kaipanla_quote')
        q = c.query
        store = manager.registry.get('redis.store')
        q.plan = AsyncMock(return_value=(stocks, [date(2021, 1, 4)]))
        q.suspension_plan = AsyncMock(return_value={s['code']+'.'+s['market']:set() for s in stocks})
        async def request(method, url, **options):
            if 'eastmoney.com' in url:
                selected = options['params']['filter']
                code, market, listed, state = '000001', 'SZ', '1991-04-03', '0'
                if '001381' in selected:
                    code, listed, state = '001381', '2021-01-04' if newly_listed else None, '0' if newly_listed else '9'
                elif '689009' in selected:
                    code, market, listed = '689009', 'SH', '2020-10-29'
                elif '920157' in selected:
                    code, market, listed, state = '920157', 'BJ', tomorrow, '9'
                return httpx.Response(200, json=dict(success=True, result=dict(count=1,pages=1,data=[
                    dict(SECUCODE=code+'.'+market,SECURITY_CODE=code,LISTING_DATE=listed+' 00:00:00' if listed else None,LISTING_STATE=state)])))
            code = options['attempt_options']()['data']['StockID']
            calls.append(code)
            return httpx.Response(200, json={**source('quote'), 'code': code})
        c.http = prefetch_http(request=request)
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
        assert result['phase'] == 'complete' and result['unlisted_without_date'] == 1
        assert set(calls) == {'000001', '689009'}
        for code, market in [('000001','SZ'),('689009','SH')]:
            assert (await q.day(market,code,'2021-01-04'))['data']['data'] == business_row('quote')['data']
        assert await q.day('SZ','001381','2021-01-04') is None
        assert await q.day('BJ','920157','2021-01-04') is None
        assert await store.client.xlen(store.stream) == 0
        newly_listed = True
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
        assert result['phase'] == 'complete' and result['unlisted_without_date'] == 0
        assert await q.day('SZ','001381','2021-01-04') is not None
        assert await store.client.xlen(store.stream) == 0
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace']+':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace']+':') for k in keys)
                await client.delete(*keys)
            await client.aclose()

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_each_source_no_dml_revision_old_response_and_ack_replay(kind, monkeypatch):
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    dataset = ProductDataset(kind)
    store = mysql = None
    try:
        await manager.start('collector.kaipanla_' + kind)
        query = manager.entries['data.kaipanla_' + kind].plugin
        archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
        mysql = query.mysql
        ingest = manager.registry.get('ingest.publish')
        async def publish(row, observed):
            batch = uuid4().hex
            envelope = make_envelope(source='kaipanla', dataset='kaipanla.' + kind + '.day',
                business_key=identity(row), job_key=dataset.JOB, run_id=batch, batch_id=batch,
                payload=dict(page=1, rows=[row])).model_copy(update={'observed_at': observed})
            state = await ingest.checkpoint(dataset.JOB)
            await ingest.publish_page([envelope], job_key=dataset.JOB,
                expected_revision=state['revision'], cursor={'test_batch': batch})
            await archive.flush()
        row, now = business_row(kind), datetime.now(UTC) - timedelta(minutes=10)
        await publish(row, now)
        assert (await query.day('SZ', '000001', '2021-01-04'))['data'] == row
        writes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'stock_market_day' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(mysql.engine, 'before_cursor_execute', capture)
        try:
            changed_metadata = {**row, 'metadata': {**row['metadata'], 'time2': 12345678}}
            await publish(changed_metadata, now + timedelta(minutes=1))
            assert not writes
            await archive.fingerprints.invalidate(dataset.FINGERPRINT_NAMESPACE, 'kaipanla')
            await publish(changed_metadata, now + timedelta(minutes=2))
            assert not writes
            # SQL-confirmed no-change B is newer than an intervening changed C,
            # even after the disposable fingerprint is explicitly lost.
            intervening = copy.deepcopy(row)
            if kind == 'quote':
                intervening['data']['real']['last_px'] += .01
            else:
                intervening['data'][PRODUCTS[kind].field][0][1] += 1
            await archive.fingerprints.invalidate(dataset.FINGERPRINT_NAMESPACE, 'kaipanla')
            await publish(intervening, now + timedelta(minutes=1, seconds=30))
            assert not writes
            assert (await query.day('SZ', '000001', '2021-01-04'))['data']['data'] == row['data']
            changed = copy.deepcopy(row)
            if kind == 'quote':
                changed['data']['real']['last_px'] += .01
            else:
                changed['data'][PRODUCTS[kind].field][0][1] += 1
            await publish(changed, now + timedelta(minutes=4))
            assert writes
            count = len(writes)
            await archive.fingerprints.invalidate(dataset.FINGERPRINT_NAMESPACE, 'kaipanla')
            await publish(row, now + timedelta(minutes=3))
            assert len(writes) == count
            assert (await query.day('SZ', '000001', '2021-01-04'))['data']['data'] == changed['data']
            # Commit succeeds, then Redis ACK fails; replay performs no business DML.
            acknowledge = archive.acknowledge
            from unittest.mock import AsyncMock
            monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack failure')))
            with pytest.raises(RuntimeError, match='ack failure'):
                await publish(changed, now + timedelta(minutes=5))
            assert await store.client.xlen(store.stream) == 1
            monkeypatch.setattr(archive, 'acknowledge', acknowledge)
            await archive.flush()
            assert len(writes) == count and await store.client.xlen(store.stream) == 0
        finally:
            event.remove(mysql.engine, 'before_cursor_execute', capture)
    finally:
        if store and store.client:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_explicit_split_preserves_both_arrays_and_disables_new_tasks():
    from empire.plugins.datasets.intraday import digest
    from empire.plugins.infra.mysql_store import make_engine
    from scripts.migrate_kaipanla_products import migrate
    from tests.test_kaipanla_intraday import row
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    value = row()
    try:
        with engine.begin() as conn:
            import json
            from pathlib import Path
            conn.exec_driver_sql(Path('sql/legacy/intraday-v2.sql').read_text('utf-8'))
            conn.execute(text('INSERT INTO stock_intraday VALUES(:code,:day,:payload,:hash,:observed)'),
                dict(code='000001.SZ', day='2021-01-04', payload=json.dumps(value),
                     hash=digest(value), observed=datetime.now()))
        assert migrate(engine, cfg['redis']['namespace'])['old_rows'] == 1
        assert migrate(engine, cfg['redis']['namespace'], apply=True)['verified_products'] == 2
        with engine.connect() as conn:
            from sqlalchemy import inspect
            assert not inspect(conn).has_table('stock_intraday')
            assert conn.execute(text('SELECT COUNT(*) FROM stock_market_day')).scalar_one() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM app_setting WHERE kind='task' AND JSON_EXTRACT(payload,'$.enabled')=false")).scalar_one() == 7
        assert migrate(engine, cfg['redis']['namespace'], apply=True)['old_rows'] == 0
    finally:
        engine.dispose()


async def test_task_rule_upgrade_is_atomic_preserves_choices_and_repeats_without_dml():
    from types import SimpleNamespace

    from empire.plugins.infra.mysql_store import make_engine
    from empire.plugins.infra.settings import SettingsStore
    from scripts.configure_kaipanla_task_defaults import migrate_database
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    store = SettingsStore(SimpleNamespace(engine=engine), cfg['redis']['namespace'])
    old = dict(enabled=True, mode='daily', interval_seconds=86400, daily_time='16:00',
               request_retries=2, use_proxy=False, proxy_fallback=False)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        store._save('task', 'kaipanla-quote', old)
        untouched = {**old, 'mode': 'manual'}
        store._save('task', 'sina-news', untouched)
        writes.clear()
        dry = migrate_database(engine, cfg['redis']['namespace'])
        assert len(dry['changed']) == 7 and not writes
        actual = migrate_database(engine, cfg['redis']['namespace'], apply=True)
        assert actual['policies']['kaipanla-quote']['enabled'] is True
        assert actual['policies']['kaipanla-quote']['use_proxy'] is False
        assert store._load('task')['sina-news'] == untouched
        writes.clear()
        assert not migrate_database(engine, cfg['redis']['namespace'], apply=True)['changed']
        assert writes == []
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
        engine.dispose()


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_weekly_collector_round_to_query_and_following_sql_only_round(kind, monkeypatch):
    from datetime import date
    from unittest.mock import AsyncMock

    from tests.test_kaipanla_intraday import STOCK
    from tests.test_kaipanla_products import product_collector
    cfg = load_config()
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start('collector.kaipanla_' + kind)
        c = manager.registry.get('collector.kaipanla_' + kind)
        archive = manager.registry.get('archive.worker')
        store = manager.registry.get('redis.store')
        days = [date(2021, 1, 4), date(2021, 1, 5)]
        monkeypatch.setattr(c.query, 'plan', AsyncMock(return_value=([STOCK], days)))
        monkeypatch.setattr(c.query, 'suspension_plan', AsyncMock(return_value={'000001.SZ': set()}))
        # Simulated source HTTP, actual normalizer, atomic Redis, archiver and SQL query.
        c.http = product_collector(kind).http
        status = c.confirmation.page_status
        async def confirmed(*args):
            await archive.flush()
            return await status(*args)
        monkeypatch.setattr(c.confirmation, 'page_status', confirmed)
        first = await c.execute()
        assert first['last_review'] == first['review_token']
        for day in days:
            assert (await c.query.day('SZ', '000001', day.isoformat()))['data']['trade_date'] == day.isoformat()
        assert await store.client.xlen(store.stream) == 0
        writes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(c.query.mysql.engine, 'before_cursor_execute', capture)
        try:
            c.http.request.reset_mock()
            second = await c.execute(baseline_revision=await c.checkpoint_revision())
            assert second['pages'] == 0 and second['phase'] == 'complete'
            assert not writes
            assert not any('longhuvip' in call.args[1] for call in c.http.request.call_args_list)
            assert await store.client.xlen(store.stream) == 0
        finally:
            event.remove(c.query.mysql.engine, 'before_cursor_execute', capture)
    finally:
        if store and store.client:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                await store.client.delete(*keys)
        await manager.shutdown()
