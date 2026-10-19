"""Listing-state source semantics, complete sets, lifecycle and ordered publication."""

import copy
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.data import make_envelope
from empire.contracts.listing_status import DATASET, FIRST, JOB, SOURCE_TYPES, bounds, months
from empire.plugins.collectors.tdx_listing_status import TdxListingStatusCollector
from empire.plugins.collectors.tdx_listing_status_source import parse, request_body
from empire.plugins.datasets import listing_status as mapping
from tests.prefetch_source import prefetch_http


def source(day, rows=None, count=None):
    rows = rows or []
    return dict(ErrorCode=0, ResultSets=[
        dict(Count=len(rows), ColName=['sc', 'code', 'name', 'sjcontent', 'sj'], Content=rows),
        dict(Count=1, ColName=['page', 'sflag', 'sdate', 'stype'], Content=[[1, 'mrtbts', day, 'zthfss']]),
        dict(Count=1, ColName=['count'], Content=[[len(rows) if count is None else count]])])


def row(label='终止上市日', reason='来源说明', code='000588', market=0):
    return [market, code, '来源简称', reason, label]


def envelope(day='2001-06-15', values=None, end='2001-06-30', page=1):
    rows, _ = parse(source(day, [row()] if values is None else values), day)
    a, b = bounds(end[:7], date.fromisoformat(end))
    counts = [0] * ((b - a).days + 1)
    counts[(date.fromisoformat(day) - a).days] = len(rows)
    return make_envelope(source='tdx', dataset=DATASET, job_key=JOB, run_id='run', batch_id='batch',
        business_key=end[:7], payload=dict(page=page, month=end[:7], end=end, rows=rows, source_counts=counts))


@pytest.mark.parametrize('label,kind', SOURCE_TYPES.items())
def test_distinguish_three_event_types_and_preserve_unknown_reason(label, kind):
    rows, total = parse(source('2020-05-22', [row(label=label, reason=None)]), '2020-05-22')
    assert total == 1 and rows[0][2] == kind and rows[0][5] is None
    assert rows[0][0] == '2020-05-22' and rows[0][1] == '000588.SZ'


def test_parallel_reasons_preserved_exact_duplicates_and_equal_count_wrong_set_rejected():
    values = [row(reason='甲'), row(reason='乙')]
    rows, _ = parse(source('2001-06-15', values), '2001-06-15')
    assert len({r[3] for r in rows}) == 2
    with pytest.raises(ValueError, match='重复'):
        parse(source('2001-06-15', [values[0], values[0]], count=2), '2001-06-15')


def test_market_count_excludes_b_and_bj_declared_outside_scope():
    values = [row(), row(code='200001'), row(code='900001', market=1), row(code='832317', market=2)]
    rows, total = parse(source('2001-06-15', values), '2001-06-15')
    assert len(rows) == total == 1


def test_bj_only_source_total_is_checked_before_scope_filter():
    values = [row(code='832317', market=2)]
    assert parse(source('2022-04-26', values), '2022-04-26') == ([], 0)
    with pytest.raises(ValueError, match='完整来源集合'):
        parse(source('2022-04-26', values, count=0), '2022-04-26')
    with pytest.raises(ValueError, match='完整来源集合'):
        parse(source('2022-04-26', [row(), *values], count=1), '2022-04-26')


@pytest.mark.parametrize('case', ['date', 'page', 'kind', 'count', 'columns', 'truncated', 'unknown', 'name', 'description'])
def test_invalid_source_evidence(case):
    body = source('2001-06-15', [row()])
    sets = body['ResultSets']
    if case == 'date':
        sets[1]['Content'][0][2] = '2001-06-16'
    elif case == 'page':
        sets[1]['Content'][0][0] = 2
    elif case == 'kind':
        sets[1]['Content'][0][3] = 'hstfp'
    elif case == 'count':
        sets[2]['Content'] = [[2]]
    elif case == 'columns':
        sets[0]['ColName'][0] = 'unknown'
    elif case == 'truncated':
        sets[0].update(Count=1000, Content=[row()] * 1000)
        sets[2]['Content'] = [[1000]]
    elif case == 'unknown':
        sets[0]['Content'][0][4] = '重新上市日'
    elif case == 'name':
        sets[0]['Content'][0][2] = ''
    else:
        sets[0]['Content'][0][3] = '长' * 2001
    with pytest.raises(ValueError):
        parse(body, '2001-06-15')


def test_month_proof_binds_every_date_and_request_once_contract():
    e = envelope()
    assert mapping.normalize(e)['row_count'] == 1
    broken = copy.deepcopy(e.raw_payload)
    broken['source_counts'].pop()
    with pytest.raises(ValueError, match='日期集合'):
        mapping.normalize(e.model_copy(update={'raw_payload': broken}))
    broken = copy.deepcopy(e.raw_payload)
    broken['source_counts'][14], broken['source_counts'][15] = 0, 1
    with pytest.raises(ValueError, match='不一致'):
        mapping.normalize(e.model_copy(update={'raw_payload': broken}))
    assert json.loads(request_body('2001-06-15'))['Params'] == ['mrtbts', 'zthfss', '2001-06-15', '1', '1', '1000']
    assert len(months(date(2026, 10, 6))) == 431
    assert bounds('1990-12', date(1990, 12, 31))[0] == FIRST


class Queue:
    def __init__(self):
        self.state = dict(revision=0, cursor={})
        self.events = []
        self.ensure_capacity = AsyncMock()
        self.fail = False

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def advance_checkpoint(self, *, job_key, expected_revision, cursor):
        assert expected_revision == self.state['revision']
        self.state = dict(revision=expected_revision + 1, cursor=cursor)
        return copy.deepcopy(self.state)

    async def publish_page(self, events, *, job_key, expected_revision, cursor, reservation=None):
        if self.fail:
            raise RuntimeError('publish failed')
        self.events.extend(events)
        return await self.advance_checkpoint(job_key=job_key, expected_revision=expected_revision, cursor=cursor)


def collector(through=date(1991, 1, 2)):
    c = TdxListingStatusCollector(lambda: through)
    c.ingest = Queue()
    c.query = SimpleNamespace(plan=AsyncMock(return_value=['1990-12', '1991-01']))
    c.records = SimpleNamespace(sanitize_text=str, error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value=dict(status='complete')))
    def response(*a, **kw):
        day = json.loads(kw['content'])['Params'][2]
        return httpx.Response(200, json=source(day, [row()] if day == '1991-01-01' else []))
    c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
    return c


async def test_all_months_publish_before_confirmation_no_day_double_read():
    c = collector()
    async def confirm(*args):
        assert len(c.ingest.events) == 2 and c.http.request.await_count == 15
        return dict(status='complete')
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result['phase'] == 'complete' and result['collected'] == 1 and result['dates_checked'] == 15
    assert len(json.dumps(result).encode()) < 1024


async def test_failed_day_retains_month_then_resume_without_waiting_previous_archive():
    c = collector()
    original = c.http.request.side_effect
    def failed(*a, **kw):
        if json.loads(kw['content'])['Params'][2] == '1991-01-01':
            return httpx.Response(200, json=source('1991-01-01', [row(), row()], count=2))
        return original(*a, **kw)
    c.http.request.side_effect = failed
    with pytest.raises(ValueError, match='重复'):
        await c.execute()
    assert c.ingest.state['cursor']['next_month'] == '1991-01' and len(c.ingest.events) == 1
    assert not c.confirmation.page_status.await_count
    c.http.request.side_effect = original
    before = c.http.request.await_count
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.http.request.await_count - before == 2 and len(c.ingest.events) == 2


async def test_published_round_recovery_skips_network_and_fresh_conflict_is_explicit():
    c = collector()
    c.confirmation.page_status.side_effect = RuntimeError('confirmation failed')
    with pytest.raises(RuntimeError, match='confirmation'):
        await c.execute()
    assert c.ingest.state['cursor']['phase'] == 'awaiting_archive'
    before = c.http.request.await_count
    with pytest.raises(ValueError, match='范围冲突'):
        await c.execute(fresh=True)
    c.confirmation.page_status.side_effect = None
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.http.request.await_count == before


async def test_failed_publication_never_advances_month():
    c = collector()
    c.ingest.fail = True
    with pytest.raises(RuntimeError, match='publish failed'):
        await c.execute()
    assert c.ingest.state['cursor']['next_month'] == '1990-12' and not c.ingest.events


def test_registration_schedule_isolation_and_mysql_only_browser():
    from empire.bootstrap import build_manager
    from empire.contracts.data import UnsupportedSchema
    from empire.contracts.listing_status import PROJECT
    from tests.catalog_factory import builtin_catalog
    cfg = dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={})
    manager = build_manager(cfg)
    task = manager.entries['collection.control'].plugin.definitions[PROJECT]
    assert task.default_schedule.mode == 'daily' and task.default_schedule.daily_time == '18:00'
    q = manager.entries['data.listing_status'].plugin
    assert q.manifest.requires == ('mysql.store',)
    e = envelope().model_copy(update={'schema_version': 2})
    catalog = builtin_catalog()
    assert catalog.schema_owner(e) == PROJECT
    with pytest.raises(UnsupportedSchema):
        catalog.mapping(e)


def test_ui_lazy_read_scope_filter_draft_and_restore():
    from concurrent.futures import Future

    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.listing_status import ListingStatusPage, ListingStatusUiPlugin
    app = QApplication.instance() or QApplication([])
    queries = []
    def invoke(*args):
        queries.append(args)
        future = Future()
        future.set_result(dict(rows=[dict(event_date='2001-06-15', unified_code='000588.SZ',
            event_type='terminated', record_key='a'*64, name='来源简称')], next=None)
            if args[1] == 'list_events' else dict(found=True, description=None))
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={}, shutting_down=False)
    assert ListingStatusUiPlugin().create_pages()[0].id == 'listing_status' and not queries
    page = ListingStatusPage(shell)
    page.show()
    app.processEvents()
    page.tick()
    page.code.setText('600000')
    page.start.setText('2001-01-01')
    page.tick()
    assert page.table.item(0, 2).text() == '终止上市' and page.code.text() == '600000'
    page.table.selectRow(0)
    page.tick()
    assert page.description.text() == '来源未提供说明。'
    page.kind.setCurrentIndex(3)
    page.find()
    assert not page.previous.isEnabled() and not page.next.isEnabled()
    state = page.save_ui_state()
    other = ListingStatusPage(shell)
    other.restore_ui_state(state)
    assert other.code.text() == '600000' and other.kind.currentData() == 'terminated'
    assert other.start.text() == '2001-01-01'
    for p in (page, other):
        p.timer.stop()
        p.close()
        p.deleteLater()
