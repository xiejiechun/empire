import asyncio
import copy
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors.tdx_suspensions import (
    API_URL,
    TdxSuspensionCollector,
    merge_event,
    parse_page,
)
from empire.plugins.data.suspensions import SuspensionDataPlugin, periods_between
from empire.plugins.datasets.suspensions import (
    classify_suspension,
    event_identity,
    normalize_source_row,
)
from tests.catalog_factory import builtin_catalog
from tests.prefetch_source import prefetch_http

COLS = ["sc", "code", "name", "fprq", "sj", "sjcontent", "tprq"]


def response(day, page, rows, *, count=None, metadata=None):
    sets = [
        {"Count": len(rows), "ColName": COLS, "Content": rows},
        {"Count": 1, "ColName": ["page", "sflag", "sdate", "stype"],
         "Content": [metadata or [page, "mrtbts", day, "hstfp"]]},
    ]
    if count is not None:
        sets.append({"Count": 1, "ColName": ["count"], "Content": [[count]]})
    return httpx.Response(200, request=httpx.Request("POST", API_URL),
                          json={"ErrorCode": 0, "ResultSets": sets})


def source_row(code="300096", *, resumed="2026-09-28 09:30", note="停牌1天",
               start="2026-09-24 09:30", market=0):
    return [market, code, "易联众", resumed, note, "撤销其他风险警示", start]


def test_page_contract_and_a_share_filtering_are_strict():
    rows, total = parse_page(response("2026-09-24", 1, [source_row()], count=1),
                             "2026-09-24", 1, initial=True)
    assert total == 1 and normalize_source_row(rows[0])["market"] == "SZ"
    assert normalize_source_row(dict(zip(COLS, source_row("200001"), strict=True))) is None
    assert normalize_source_row(dict(zip(
        COLS, source_row("832317", market=2), strict=True))) is None
    with pytest.raises(ValueError, match="市场或证券代码无效"):
        normalize_source_row(dict(zip(COLS, source_row("832317", market=3), strict=True)))
    with pytest.raises(ValueError, match="页码不匹配"):
        parse_page(response("2026-09-24", 1, [], count=0,
                            metadata=[2, "mrtbts", "2026-09-24", "hstfp"]),
                   "2026-09-24", 1, initial=True)
    with pytest.raises(ValueError, match="结果集"):
        parse_page(response("2026-09-24", 2, []), "2026-09-24", 2, initial=True)


@pytest.mark.parametrize('beijing_code', ['430047', '832317', '920169'])
async def test_collection_counts_complete_source_rows_before_filtering_beijing_market(beijing_code):
    collector = TdxSuspensionCollector()
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    collector._request_page = AsyncMock(side_effect=[
        ([dict(zip(COLS, source_row("000401"), strict=True)),
          dict(zip(COLS, source_row(beijing_code, market=2), strict=True))], 2),
        ([], None),
    ])

    rows, pages = await collector._collect_day("2021-10-21")

    assert pages == 1
    assert [row["code"] for row in rows] == ["000401"]


async def test_collection_count_excludes_b_shares_returned_in_source_pages():
    collector = TdxSuspensionCollector()
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    collector._request_page = AsyncMock(side_effect=[
        ([dict(zip(COLS, source_row("000959"), strict=True)),
          dict(zip(COLS, source_row("600145", market=1), strict=True)),
          dict(zip(COLS, source_row("900933", market=1), strict=True))], 2),
        ([], None),
    ])

    rows, pages = await collector._collect_day("2022-03-03")

    assert pages == 1
    assert [row["code"] for row in rows] == ["000959", "600145"]


async def test_collection_rejects_missing_reported_a_share():
    collector = TdxSuspensionCollector()
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    collector._request_page = AsyncMock(side_effect=[
        ([dict(zip(COLS, source_row("000401"), strict=True))], 2),
        ([], None),
    ])

    with pytest.raises(ValueError, match="来源报告 2 条，分页取得 1 条"):
        await collector._collect_day("2021-10-21")


def test_archive_batch_cannot_cross_the_declared_month():
    from empire.contracts.data import make_envelope

    event = make_envelope(
        source="tdx", dataset="suspensions.period", job_key="tdx-suspensions-v1", schema_version=3,
        business_key="bad-period", run_id="run", batch_id="batch",
        payload={"page": 1, "period": "2026-09", "start_date": "2026-09-30",
                 "end_date": "2026-10-01", "checked_dates": ["2026-09-30", "2026-10-01"],
                 "rows": []},
    )
    with pytest.raises(ValueError, match="单一自然月"):
        builtin_catalog().normalize(event)


def test_suspension_type_and_resume_merge_rules():
    assert classify_suspension("临时停牌", "2026-09-24T10:15+08:00",
                               "2026-09-24T13:00+08:00") == "intraday"
    assert classify_suspension("停牌1天", "2026-09-24T09:30+08:00",
                               "2026-09-28T09:30+08:00") == "full_day"
    pending = normalize_source_row(dict(zip(COLS, source_row(resumed=None), strict=True)))
    complete = normalize_source_row(dict(zip(COLS, source_row(), strict=True)))
    assert event_identity(pending) != event_identity(complete)
    assert event_identity(complete) != event_identity({**complete, "reason": "另一原因"})
    with pytest.raises(ValueError, match="冲突"):
        merge_event(complete, {**complete, "name": "另一简称"})


def test_historical_same_day_resume_takes_precedence_over_day_label():
    raw = {"sc": 0, "code": "000921", "name": "海信家电",
           "fprq": "2005-06-17 10:30", "sj": "停牌1天",
           "sjcontent": "澄清公告", "tprq": "2005-06-17 09:30"}
    row = normalize_source_row(raw)
    assert row["suspension_type"] == "intraday"
    assert row["source_note"] == "停牌1天"
    assert row["resumed_at"] == "2005-06-17T10:30+08:00"
    from empire.plugins.datasets.suspensions import validate_period
    row = {**row, 'source_dates': ['2005-06-17']}
    assert validate_period("2005-06-17", "2005-06-17", ["2005-06-17"], [row]) == [row]
    with pytest.raises(ValueError, match="复牌时间早于停牌时间"):
        normalize_source_row({**raw, "fprq": "2005-06-17 09:00"})


@pytest.mark.parametrize('note', [None, '', '  '])
def test_missing_historical_note_is_optional_without_inventing_resume(note):
    from empire.plugins.datasets.suspensions import validate_period
    raw = {'sc': 0, 'code': '000950', 'name': '重药控股', 'fprq': None,
           'sj': note, 'sjcontent': '临时停牌', 'tprq': '2005-10-10 09:30'}
    row = normalize_source_row(raw)
    assert row['source_note'] == '' and row['resumed_at'] is None
    assert row['reason'] == '临时停牌' and row['suspension_type'] == 'full_day'
    row = {**row, 'source_dates': ['2005-10-10']}
    assert validate_period('2005-10-10', '2005-10-10', ['2005-10-10'], [row]) == [row]
    assert normalize_source_row({**raw, 'fprq': '2005-10-10 10:30'})['suspension_type'] == 'intraday'


@pytest.mark.parametrize('note', [1, [], {}, False])
def test_invalid_note_type_has_field_error_not_attribute_error(note):
    raw = dict(zip(COLS, source_row(), strict=True))
    with pytest.raises(ValueError, match='停牌说明类型无效'):
        normalize_source_row({**raw, 'sj': note})


@pytest.mark.parametrize('reason', [None, '', '  '])
def test_missing_historical_reason_is_optional(reason):
    raw = {'sc': 0, 'code': '000602', 'name': '金马集团',
           'fprq': '2006-05-08 09:30', 'sj': '停牌今起复牌',
           'sjcontent': reason, 'tprq': '2006-05-08 09:30'}
    row = normalize_source_row(raw)
    assert row['reason'] == ''
    assert row['suspension_type'] == 'intraday'


@pytest.mark.parametrize('reason', [1, [], {}, False])
def test_invalid_reason_type_is_rejected(reason):
    raw = dict(zip(COLS, source_row(), strict=True))
    with pytest.raises(ValueError, match='停牌原因无效'):
        normalize_source_row({**raw, 'sjcontent': reason})


def test_month_keeps_distinct_source_rows_and_rejects_exact_identity_conflicts():
    from empire.plugins.collectors.suspension_batches import bounded_batches
    raw = {'sc': 0, 'code': '000659', 'name': '珠海中富', 'fprq': None,
           'sj': '今起停牌', 'sjcontent': '相关股东会议特别提示', 'tprq': '2005-10-10 09:30'}
    suspended = normalize_source_row(raw)
    resumed = normalize_source_row({**raw, 'fprq': '2005-10-27 09:30', 'sj': '今起复牌',
                                    'sjcontent': '股权分置改革股票简称变更公告'})
    other = {**resumed, 'resumed_at': '2005-10-28T09:30+08:00'}
    days = [('2005-10-10', [suspended], 1), ('2005-10-27', [resumed], 1), ('2005-10-28', [other], 1)]
    result = bounded_batches(days, source='tdx', job_key='test', batch_id='test', first_page=1,
                             limit=524288, source_url=API_URL, merge=merge_event)
    assert len(result[0][0].raw_payload['rows']) == 3
    assert len({event_identity(row) for row in result[0][0].raw_payload['rows']}) == 3
    same_time_other_source_record = {**resumed, 'source_note': '停牌1小时',
                                     'reason': '交易异常波动'}
    assert event_identity(resumed) != event_identity(same_time_other_source_record)
    with pytest.raises(ValueError, match='内容冲突'):
        merge_event(resumed, {**resumed, 'name': '另一简称'})


def test_same_time_tdx_rows_with_different_descriptions_are_both_kept():
    from empire.plugins.collectors.suspension_batches import bounded_batches
    first = normalize_source_row({'sc': 1, 'code': '600113', 'name': '浙江东日',
        'fprq': '2012-05-02 10:30', 'sj': '今起复牌', 'sjcontent': '重要事项',
        'tprq': '2012-05-02 09:30'})
    second = normalize_source_row({'sc': 1, 'code': '600113', 'name': '浙江东日',
        'fprq': '2012-05-02 10:30', 'sj': '停牌1小时', 'sjcontent': '交易异常波动',
        'tprq': '2012-05-02 09:30'})
    result = bounded_batches([('2012-05-02', [first, second], 1)], source='tdx',
        job_key='test', batch_id='test', first_page=1, limit=524288,
        source_url=API_URL, merge=merge_event)
    assert result[0][0].raw_payload['rows'] == sorted(
        [{**row, 'source_dates': ['2012-05-02']} for row in [first, second]], key=event_identity)


async def test_plan_initializes_from_2004_and_normal_run_rechecks_last_sql_date():
    query = SuspensionDataPlugin()
    query.mysql = SimpleNamespace(control=AsyncMock(return_value={}))
    plan = await query.plan(date(2005, 2, 2))
    assert plan["start_date"] == "2004-12-27"
    assert plan["periods"] == [
        {"period": "2004-12", "start_date": "2004-12-27", "end_date": "2004-12-31"},
        {"period": "2005-01", "start_date": "2005-01-01", "end_date": "2005-01-31"},
        {"period": "2005-02", "start_date": "2005-02-01", "end_date": "2005-02-02"},
    ]
    query.mysql.control.return_value = {"coverage": {"through": "2005-02-01"}}
    maintenance = await query.plan(date(2005, 2, 2))
    assert maintenance["start_date"] == "2005-02-01"
    assert maintenance["expected_days"] == 2
    assert (await query.plan(date(2005, 2, 2), fresh=True))["start_date"] == "2004-12-27"
    assert periods_between(date(2024, 2, 28), date(2024, 3, 1))[-1]["period"] == "2024-03"


class MemoryIngest:
    def __init__(self):
        self.state = {"revision": 0, "cursor": {}}
        self.events = []

    async def checkpoint(self, job_key):
        return copy.deepcopy(self.state)

    async def ensure_capacity(self, incoming=1, reservation=None):
        return None

    async def publish_page(self, events, *, job_key, expected_revision, cursor, reservation=None):
        for event in events:
            builtin_catalog().normalize(event)
        self.events.extend(events)
        return await self.advance_checkpoint(job_key=job_key, expected_revision=expected_revision,
                                             cursor=cursor)

    async def advance_checkpoint(self, *, job_key, expected_revision, cursor):
        assert len(json.dumps(cursor, ensure_ascii=False).encode()) <= 16384
        assert expected_revision == self.state["revision"]
        self.state = {"revision": expected_revision + 1, "cursor": copy.deepcopy(cursor)}
        return copy.deepcopy(self.state)


def collector():
    item = TdxSuspensionCollector(today=lambda: date(2026, 9, 25))
    item.ingest = MemoryIngest()
    item.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    item.query = SimpleNamespace(plan=AsyncMock(return_value={
        "periods": [{"period": "2026-09", "start_date": "2026-09-24",
                     "end_date": "2026-09-25"}],
        "start_date": "2026-09-24", "end_date": "2026-09-25", "expected_days": 2,
        "coverage_through": "2026-09-24",
    }))
    item.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    return item


async def test_collector_reads_complete_day_counts_only_a_shares_and_waits_for_archive():
    item = collector()
    calls = []

    async def request(day, page):
        calls.append((day, page))
        if page == 2:
            return [], None
        if day == "2026-09-24":
            return [dict(zip(COLS, source_row(resumed=None), strict=True)),
                    dict(zip(COLS, source_row("200001"), strict=True))], 1
        return [dict(zip(COLS, source_row(), strict=True))], 1

    item._request_page = request
    item.http = prefetch_http()
    async def download(day, **kw):
        return await item._collect_day(day)
    item.download_day = download
    result = await item.execute()
    assert calls == [("2026-09-24", 1), ("2026-09-25", 1)]
    assert result["dates_checked"] == 2 and result["collected"] == 2
    assert {row['resumed_at'] for row in item.ingest.events[0].raw_payload['rows']} == {
        None, '2026-09-28T09:30+08:00'}
    item.confirmation.page_status.assert_awaited_once()
    assert item.ingest.state["cursor"]["phase"] == "complete"


async def test_failed_date_does_not_publish_partial_month_or_advance_checkpoint():
    item = collector()

    async def request(day, page):
        if day == "2026-09-25":
            raise ValueError("source failed")
        return ([dict(zip(COLS, source_row(), strict=True))], 1) if page == 1 else ([], None)

    item._request_page = request
    item.http = prefetch_http()
    async def download(day, **kw):
        return await item._collect_day(day)
    item.download_day = download
    with pytest.raises(ValueError, match="source failed"):
        await item.execute()
    assert not item.ingest.events
    assert item.ingest.state == {"revision": 0, "cursor": {}}
    assert item.records.add_error.call_args.kwargs["metadata"]["date"] == "2026-09-25"


async def test_full_history_checkpoints_remain_small_and_cover_every_date():
    item = collector()
    query = SuspensionDataPlugin()
    query.mysql = SimpleNamespace(control=AsyncMock(return_value={}))
    item.query = query
    seen = []
    async def collect(day, **options):
        seen.append(day)
        return [], 1
    item.http = prefetch_http()
    item.download_day = collect
    result = await item.execute()
    assert seen[0] == '2004-12-27' and seen[-1] == '2026-09-25'
    assert len(seen) == (date(2026, 9, 25) - date(2004, 12, 27)).days + 1
    assert len(set(seen)) == len(seen) == result['dates_checked']
    assert 'periods' not in item.ingest.state['cursor']
    assert len(json.dumps(item.ingest.state['cursor']).encode()) < 1024


async def test_source_duplicate_cannot_hide_missing_record_but_distinct_descriptions_remain():
    item = collector()
    row = dict(zip(COLS, source_row(), strict=True))
    item._request_page = AsyncMock(side_effect=[([row, row], 2), ([], None)])
    with pytest.raises(ValueError, match='业务键重复'):
        await item._collect_day('2026-09-24')
    item._request_page = AsyncMock(side_effect=[([row, row], 1), ([], None)])
    with pytest.raises(ValueError, match='分页取得'):
        await item._collect_day('2026-09-24')
    item._request_page = AsyncMock(side_effect=[([row, {**row, 'sjcontent': '冲突'}], 2), ([], None)])
    rows, _ = await item._collect_day('2026-09-24')
    assert len(rows) == 2


async def test_identical_source_repetitions_require_complete_repeat_confirmation():
    item = collector()
    row = dict(zip(COLS, source_row(), strict=True))
    item._request_page = AsyncMock(side_effect=[([row, row], 2), ([row, row], 2)])
    rows, requests = await item._collect_day('2014-05-16')
    assert len(rows) == 1 and requests == 2
    item._request_page = AsyncMock(side_effect=[([row, row], 2),
                                              ([row, {**row, 'code': '000001'}], 2)])
    with pytest.raises(ValueError, match='复核不一致'):
        await item._collect_day('2014-05-16')


async def test_full_day_expansion_replaces_partial_set_and_never_offsets(monkeypatch):
    monkeypatch.setattr('empire.plugins.collectors.tdx_suspensions.PAGE_SIZE', 2)
    item = collector()
    first = dict(zip(COLS, source_row(), strict=True))
    other = {**first, 'sjcontent': '第二条来源说明'}
    item._request_page = AsyncMock(side_effect=[([first, first], 3),
                                              ([first, other, {**first, 'code': '000001'}], 3)])
    rows, requests = await item._collect_day('2026-09-24')
    assert len(rows) == 3 and requests == 2
    assert item._request_page.call_args_list[0].args == ('2026-09-24', 1)
    assert item._request_page.call_args_list[1].kwargs == {'page_size': 4}


async def test_oversized_full_day_is_not_published(monkeypatch):
    monkeypatch.setattr('empire.plugins.collectors.tdx_suspensions.PAGE_SIZE', 2)
    monkeypatch.setattr('empire.plugins.collectors.tdx_suspensions.MAX_DAY_ROWS', 2)
    item = collector()
    item.http = prefetch_http()
    async def download(day, **kw):
        return await item._collect_day(day)
    item.download_day = download
    item._request_page = AsyncMock(return_value=(
        [dict(zip(COLS, source_row(str(code).zfill(6)), strict=True)) for code in (1, 2)], 2))
    with pytest.raises(ValueError, match='安全上限'):
        await item.execute()
    assert not item.ingest.events


async def test_large_month_splits_and_restart_begins_at_first_unpublished_date():
    item = collector()
    item.ingest.settings = {'max_page_bytes': 2400}
    dates = ['2026-09-24', '2026-09-25']
    async def collect(day, **options):
        rows = [normalize_source_row(dict(zip(COLS, source_row(f'00000{i}',
                start=day+' 09:30', resumed=None), strict=True))) for i in range(4)]
        return rows, 1
    item.http = prefetch_http()
    item.download_day = collect
    publish = item.ingest.publish_page
    async def interrupt_after_first(*args, **kwargs):
        if item.ingest.events:
            raise asyncio.CancelledError
        return await publish(*args, **kwargs)
    item.ingest.publish_page = interrupt_after_first
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    assert len(item.ingest.events) == 1
    assert item.ingest.state['cursor']['resume_date'] == dates[1]
    assert item.ingest.state['cursor']['period_index'] == 0
    resumed = collector()
    resumed.ingest = item.ingest
    resumed.ingest.publish_page = publish
    calls = []
    async def remaining(day, **options):
        calls.append(day)
        return await collect(day)
    resumed.http = prefetch_http()
    resumed.download_day = remaining
    await resumed.execute(baseline_revision=item.ingest.state['revision'])
    assert calls == dates[1:]
    assert [d for e in item.ingest.events for d in e.raw_payload['checked_dates']] == dates
    assert all(len(e.model_dump_json().encode()) <= 2400 for e in item.ingest.events)


@pytest.mark.parametrize('interrupt_at', ['fetch', 'archive', 'finalize'])
async def test_restart_reuses_published_month_and_retries_unpublished_month(interrupt_at):
    item = collector()
    item.query.plan.return_value = {
        'start_date': '2004-12-27', 'end_date': '2005-01-02',
        'periods': periods_between(date(2004, 12, 27), date(2005, 1, 2)),
    }
    calls = []
    async def collect(day, **options):
        calls.append(day)
        if interrupt_at == 'fetch' and day == '2005-01-02':
            raise asyncio.CancelledError
        return [], 1
    item.http = prefetch_http()
    item.download_day = collect
    if interrupt_at == 'archive':
        item.confirmation.page_status.side_effect = asyncio.CancelledError
    if interrupt_at == 'finalize':
        original = item.ingest.advance_checkpoint
        async def advance(**kwargs):
            if kwargs['cursor']['phase'] == 'complete':
                raise asyncio.CancelledError
            return await original(**kwargs)
        item.ingest.advance_checkpoint = advance
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    replacement = collector()
    replacement.ingest = MemoryIngest()
    replacement.ingest.state = copy.deepcopy(item.ingest.state)
    replacement.ingest.events = list(item.ingest.events)
    resumed = []
    async def resume(day, **options):
        resumed.append(day)
        return [], 1
    replacement.http = prefetch_http()
    replacement.download_day = resume
    await replacement.execute(baseline_revision=replacement.ingest.state['revision'])
    replacement.query.plan.assert_not_awaited()
    assert resumed == (['2005-01-01', '2005-01-02'] if interrupt_at == 'fetch' else [])
    assert len(replacement.ingest.events) == 2
    assert replacement.ingest.state['cursor']['phase'] == 'complete'


async def test_history_publishes_all_months_before_waiting_for_archive():
    item = collector()
    item.query.plan.return_value = {'start_date': '2004-12-27', 'end_date': '2005-02-01'}
    item.http = prefetch_http()
    item.download_day = AsyncMock(return_value=([], 1))
    async def confirm(*args):
        assert len(item.ingest.events) == 3
        assert item.ingest.state['cursor']['phase'] == 'awaiting_archive'
        raise asyncio.CancelledError
    item.confirmation.page_status.side_effect = confirm
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    item.confirmation.page_status.assert_awaited_once()
    assert item.ingest.state['cursor']['phase'] != 'complete'
