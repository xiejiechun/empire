"""Seven actual registered contracts: source → Redis → shared archiver → query."""
import copy
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.datasets.intraday import identity
from empire.plugins.datasets.kaipanla_products import ProductDataset
from tests.test_kaipanla_products import business_row

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
            conn.execute(text('INSERT INTO stock_intraday VALUES(:code,:day,:payload,:hash,:observed)'),
                dict(code='000001.SZ', day='2021-01-04', payload=json.dumps(value),
                     hash=digest(value), observed=datetime.now()))
        assert migrate(engine, cfg['redis']['namespace'])['old_rows'] == 1
        assert migrate(engine, cfg['redis']['namespace'], apply=True)['verified_products'] == 2
        with engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM stock_intraday')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM stock_market_day')).scalar_one() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM app_setting WHERE kind='task' AND JSON_EXTRACT(payload,'$.enabled')=false")).scalar_one() == 7
        assert migrate(engine, cfg['redis']['namespace'], apply=True)['old_rows'] == 0
    finally:
        engine.dispose()
