import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.contracts.listings import (
    DATASET,
    FIELDS,
    HISTORY_MAX_BYTES,
    JOB,
    PROJECT,
    digest,
    parse,
    url,
)
from empire.core.config import load_config
from empire.plugins.collectors.ths_listings import ThsListingCollector
from empire.plugins.datasets import listings

STOCKS = [dict(market='SZ', code='000001', name='平安银行'), dict(market='SH', code='600000', name='浦发银行')]


def source():
    return dict(status_code=0, data=dict(listing_date='1991-04-03', establish_date='1987-12-22',
        issuance_num='350000.0000', issuance_price='40.0000', first_day_open_price='49',
        estimated_raised='27000000.0000', actual_raised='14000000.0000', issuance_pe=None,
        winning_rate=None, lead_underwriter='机构甲,机构乙', sponsor='机构甲', history='历史沿革'))


def test_real_source_units_nulls_precision_and_market_mapping():
    row = parse(source(), STOCKS[0], '2026-10-06')
    assert row['issuance_num'] == '350000' and row['winning_rate'] is None
    assert row['issuance_price'] == '40' and row['listing_date'] == '1991-04-03'
    assert row['unified_code'] == '000001.SZ'
    assert url(STOCKS[0]).endswith('code=000001&market=33')
    assert url(STOCKS[1]).endswith('code=600000&market=17')
    assert url(dict(market='BJ', code='920009')).endswith('code=920009&market=151')
    body = source()
    body['data'].update(winning_rate='0.0200842635', issuance_pe='-1', issuance_price='0')
    row = parse(body, STOCKS[0], '2026-10-06')
    assert row['winning_rate'] == '0.0200842635' and row['issuance_pe'] == '-1' and row['issuance_price'] == '0'


def test_source_establishment_after_listing_is_preserved_with_warning():
    from empire.contracts.listings import date_warning
    body = source()
    body['data'].update(listing_date='1993-10-28', establish_date='1993-12-04')
    row = parse(body, dict(market='SZ', code='000032'), '2026-10-06')
    assert row['listing_date'] == '1993-10-28' and row['establish_date'] == '1993-12-04'
    assert date_warning(row) and not date_warning(parse(source(), STOCKS[0], '2026-10-06'))


def test_only_exact_source_empty_is_unavailable():
    from empire.contracts.listings import is_unavailable
    empty = dict(status_code=10001, data={}, status_msg='result empty')
    row = parse(empty, STOCKS[0], '2026-10-06')
    assert is_unavailable(row) and row['unified_code'] == '000001.SZ' and 'listing_date' not in row
    for change in ({'status_code': 10002}, {'status_code': '10001'}, {'status_msg': 'error'},
                   {'data': None}, {'data': {'listing_date': None}}, {'extra': True}):
        with pytest.raises(ValueError):
            parse({**empty, **change}, STOCKS[0], '2026-10-06')


@pytest.mark.parametrize('field,value', [('listing_date',None), ('listing_date','2099-01-01'),
    ('listing_date','1991-4-3'), ('establish_date','2099-01-01'), ('issuance_price','0.00001'),
    ('issuance_num','-1'), ('winning_rate','100.1'), ('winning_rate','0.00000000001'),
    ('issuance_price',True), ('history','x' * (HISTORY_MAX_BYTES+1)), ('sponsor','机'*2049), ('issuance_num','1e3')],
    ids=['missing-date','future-date','bad-date','future-establish','precision','negative','percent-high',
         'percent-precision','bool','large-history','large-sponsor','exponent'])
def test_invalid_source_fails(field, value):
    body = source()
    body['data'][field] = value
    with pytest.raises(ValueError):
        parse(body, STOCKS[0], '2026-10-06')


def test_history_utf8_boundary_preserved_and_invalid_types_rejected():
    body = source()
    history = '文' * (HISTORY_MAX_BYTES // 3) + 'x' * (HISTORY_MAX_BYTES % 3)
    body['data']['history'] = history
    assert len(history.encode()) == HISTORY_MAX_BYTES
    assert parse(body, STOCKS[0], '2026-10-06')['history'] == history
    for bad in (history + 'x', {}, 123, 'valid\x00text'):
        body['data']['history'] = bad
        with pytest.raises(ValueError, match='history'):
            parse(body, STOCKS[0], '2026-10-06')


@pytest.mark.parametrize('field', FIELDS)
def test_missing_field_is_not_source_null(field):
    body = source()
    del body['data'][field]
    with pytest.raises(ValueError):
        parse(body, STOCKS[0], '2026-10-06')


def test_unknown_empty_protocol_and_archive_identity():
    for body in ({'status_code':-1}, {'status_code':0,'data':{}}, {'status_code':0,'data':None},
                 {'status_code':True,'data':source()['data']}):
        with pytest.raises(ValueError):
            parse(body, STOCKS[0], '2026-10-06')
    row = parse(source(), STOCKS[0], '2026-10-06')
    e = make_envelope(source='ths', dataset=DATASET, business_key='SH:600000', job_key=JOB,
        run_id='test', batch_id='test', payload=dict(page=1, unit='SH:600000', row=row, manifest=None))
    with pytest.raises(ValueError):
        listings.normalize(e)


def test_registration_defaults_and_scope_contract():
    manager = build_manager(load_config('config/app.example.toml'))
    collector = manager.entries['collector.ths_listings'].plugin
    control = manager.entries['collection.control'].plugin
    task = control.definitions[PROJECT]
    assert collector.project_id == PROJECT and task.default_schedule.mode == 'daily'
    contribution = manager.entries['dataset.astock'].plugin.datasets[DATASET]
    assert contribution.projects == {JOB:PROJECT}
    assert len(json.dumps(dict(index=15000, scope_hash=digest(['x']), batch_id='a'*32, pages=15001)).encode()) < 1000


def collector():
    c = ThsListingCollector()
    state = dict(revision=0, cursor={})
    async def checkpoint(_):
        return copy.deepcopy(state)
    async def publish(events, **kw):
        state.update(revision=state['revision']+1, cursor=kw['cursor'])
        return copy.deepcopy(state)
    async def advance(**kw):
        state.update(revision=state['revision']+1, cursor=kw['cursor'])
    c.ingest = SimpleNamespace(checkpoint=checkpoint, publish_page=publish, advance_checkpoint=advance)
    c.records = SimpleNamespace(sanitize_text=str, record_error=AsyncMock())
    c.query = SimpleNamespace(plan=AsyncMock(return_value=(STOCKS, set(), {})))
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status':'complete'}))
    c.fetch = AsyncMock(side_effect=lambda stock: (parse(source(), stock, '2026-10-06'), datetime.now(UTC), url(stock)))
    return c, state


async def test_enqueue_all_before_archive_and_failure_resume(monkeypatch):
    c, state = collector()
    events = []
    async def publish(ingest, stats, envelopes, **kw):
        events.extend(envelopes)
        assert c.confirmation.page_status.await_count == 0
        return await ingest.publish_page(envelopes, **kw)
    monkeypatch.setattr('empire.plugins.collectors.ths_listings.publish_with_capacity', publish)
    c.fetch.side_effect = [(parse(source(), STOCKS[0], '2026-10-06'), datetime.now(UTC), url(STOCKS[0])), ValueError('bad second')]
    with pytest.raises(ValueError):
        await c.execute()
    assert state['cursor']['index'] == 1 and state['cursor']['pages'] == 1
    c.fetch.side_effect = lambda stock: (parse(source(), stock, '2026-10-06'), datetime.now(UTC), url(stock))
    result = await c.execute(baseline_revision=state['revision'])
    assert result['phase'] == 'complete' and len(events) == 3
    assert c.fetch.await_count == 3 and c.confirmation.page_status.await_count == 1


async def test_equal_count_different_pool_cannot_resume(monkeypatch):
    c, state = collector()
    state.update(cursor=dict(phase='fetch', scope_hash=digest(['SZ:000002','SH:600000']), index=1))
    with pytest.raises(ValueError, match='集合'):
        await c.execute()
    assert not c.fetch.await_count


async def test_daily_skip_existing_weekly_refresh_and_awaiting_resume(monkeypatch):
    c, state = collector()
    async def publish(ingest, stats, envelopes, **kw):
        return await ingest.publish_page(envelopes, **kw)
    monkeypatch.setattr('empire.plugins.collectors.ths_listings.publish_with_capacity', publish)
    c.query.plan.return_value = (STOCKS, {'SZ:000001','SH:600000'}, {'refresh_started_at':datetime.now(UTC).isoformat()})
    result = await c.execute()
    assert c.fetch.await_count == 0 and result['pages'] == 1
    state['cursor']['phase'] = 'awaiting_archive'
    c.query.plan.reset_mock()
    await c.execute(baseline_revision=state['revision'], fresh=True)
    assert not c.query.plan.await_count and c.fetch.await_count == 0
    c.query.plan.return_value = (STOCKS, {'SZ:000001','SH:600000'}, {'refresh_started_at':'2020-01-01T00:00:00+00:00'})
    await c.execute(baseline_revision=state['revision'])
    assert c.fetch.await_count == 2


def test_ui_lazy_independent_draft_and_selection_detail(monkeypatch):
    from concurrent.futures import Future

    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.listings import FIELDS as UI_FIELDS
    from empire.plugins.ui.listings import ListingPage, ListingUiPlugin
    app = QApplication.instance() or QApplication([])
    queries = []
    row = {k: None for k in UI_FIELDS}
    row.update(unified_code='000001.SZ',listing_date='1991-04-03',name='平安银行')
    def invoke(*args):
        queries.append(args)
        future = Future()
        future.set_result(dict(rows=[row],next=None) if args[1]=='list_records' else {'history':'沿革'})
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke),cfg={},shutting_down=False)
    assert ListingUiPlugin().create_pages()[0].id == 'listings' and not queries
    page = ListingPage(shell)
    page.show()
    app.processEvents()
    page.tick()
    page.code.setText('600000')
    page.tick()
    assert page.code.text() == '600000' and page.table.item(0,4).text() == ''
    page.table.selectRow(0)
    page.tick()
    assert page.body.toPlainText() == '沿革'
    assert any(q[1]=='detail' for q in queries)
    state = page.save_ui_state()
    page.find()
    assert page.selected is None
    page.restore_ui_state(state)
    assert page.code.text() == '600000'
    page.close()
    page.deleteLater()
