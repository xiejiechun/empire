"""Holder source semantics and ordered public lifecycle counterexamples."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.features.holders.collector import HolderCollector
from empire.features.holders.contract import KINDS, digest, validate
from empire.features.holders.source import parse
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher

STOCK = dict(code='601139', market='SH', unified_code='601139.SH', name='深圳燃气')


def source(code='601139', *, bond=True, pledge=False, malformed=False, count=10, name='股东', exit_order=False, tied=False, expanded=False):
    sections = []
    for kind, (_, section, tab_class) in KINDS.items():
        if kind == 'bond_holders' and not bond:
            continue
        is_bond = kind == 'bond_holders'
        headers = (['序号', '持有人名称', '持有数量(万张)', '持有比例(%)'] if is_bond else
            ['机构或基金名称', '持有数量(股)', '持股变化(股)',
             '占流通股比例' if kind == 'float_holders' else '占总股本比例'] +
            (['质押占其直接持股比'] if pledge else []) +
            ['变动比例' if kind == 'float_holders' else '实际增减持', '股份类型', '持股详情'])
        rows = []
        row_count = 11 if expanded and not is_bond else 12 if tied and not is_bond else count
        for i in range(row_count):
            values = ([str(i+1), name+str(i), '10.00', '1.00'] if is_bond else
                [name+str(i), '10.00万', '<s class="down"></s>1.00万' if i == 0 else '不变', '1.00%'] +
                (['无质押'] if pledge else []) + ['新进' if malformed else '不变', '流通A股', '点击查看'])
            if expanded and not is_bond and i == 10:
                values[1], values[3] = '9.00万', '0.90%'
            if malformed and not is_bond:
                row = '<tr>' + ''.join('<td>' + v + (' ' if j == len(values)-3 else '</td>') for j, v in enumerate(values)) + '</tr>'
            else:
                row = '<tr>' + ''.join('<td>' + v + '</td>' for v in values) + '</tr>'
            rows.append(row)
        exited = (['4', '退出人', '5', '0.50'] if is_bond else
                   ['退出人', '5.00万', '退出', '0.50%'] + ([''] if pledge else []) + ['', '', ''])
        rows += ['<tr class="m_th"><th colspan="8">较上个报告期退出前十大</th></tr>',
                 '<tr class="gray">' + ''.join('<td>'+v+'</td>' for v in exited) + '</tr>']
        if is_bond and exit_order:
            rows.append('<tr class="gray"><td>2</td><td>另一退出人</td><td>5</td><td>0.50</td></tr>')
        caption = '<caption>前十大累计持有：<em>100.00万' + ('张' if is_bond else '股') + '</em>，累计占总股本比：<em>10.00%</em></caption>'
        if tied and not is_bond:
            caption = caption.replace('100.00万', '120.00万').replace('10.00%', '12.00%')
        if expanded and not is_bond:
            caption = caption.replace('100.00万', '109.00万').replace('10.00%', '10.90%')
        table = '<table>' + caption + '<thead><tr>' + ''.join('<th>'+h+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
        block = '<div class="bd">' + ('<div class="sec">债券名称：<span>燃23转债</span></div>' if is_bond else '')
        block += f'<a class="{tab_class}" targ="{section}_1">2026-06-30</a><div class="m_tab_content2" id="{section}_1">{table}</div></div>'
        sections.append(f'<div id="{section}">{block}</div>')
    return '<html><input id="stockCode" value="' + code + '">' + ''.join(sections) + '</html>'


@pytest.mark.parametrize('kind', ['top_holders', 'float_holders'])
def test_tenth_place_ties_preserve_all_source_members_and_reject_unproven_overflow(kind):
    reports = parse(source(tied=True), kind, STOCK)
    assert len(reports[0]['members']) == 13
    assert [m['seq'] for m in reports[0]['members'][:12]] == list(range(1, 13))
    for damage in ('quantity', 'duplicate', 'summary', 'limit'):
        bad = copy.deepcopy(reports)
        if damage == 'quantity':
            bad[0]['members'][11]['quantity'] = '90000'
        elif damage == 'duplicate':
            bad[0]['members'][11]['holder_name'] = bad[0]['members'][10]['holder_name']
        elif damage == 'summary':
            bad[0]['total_quantity'] = '1000000'
        else:
            for seq in range(13, 22):
                member = copy.deepcopy(bad[0]['members'][0])
                member.update(seq=seq, holder_name='extra' + str(seq))
                bad[0]['members'].insert(seq - 1, member)
        with pytest.raises(ValueError):
            validate(kind, STOCK['unified_code'], bad)


@pytest.mark.parametrize('kind', ['top_holders', 'float_holders'])
def test_source_expansion_without_tie_requires_whole_body_totals(kind):
    report = parse(source(expanded=True), kind, STOCK)[0]
    current = report['members'][:11]
    assert current[9]['quantity'] == '100000' and current[10]['quantity'] == '90000'
    assert report['total_quantity'] == '1090000'
    assert [m['seq'] for m in current] == list(range(1, 12))
    for field, value in (('total_quantity', '1000000'), ('total_ratio', '10')):
        bad = copy.deepcopy(report)
        bad[field] = value
        with pytest.raises(ValueError, match='合计与来源汇总不符'):
            validate(kind, STOCK['unified_code'], [bad])


@pytest.mark.parametrize('kind', KINDS)
def test_large_notice_preserves_source_and_bond_count_remains_bounded(kind):
    report = parse(source(tied=True), kind, STOCK)[0]
    if kind == 'bond_holders':
        extra = copy.deepcopy(report['members'][0])
        extra.update(seq=11, source_rank=11, holder_name='额外债券持有人')
        report['members'].insert(10, extra)
        with pytest.raises(ValueError, match='名单数量无效'):
            validate(kind, STOCK['unified_code'], [report])
    else:
        report.update(report_type='change_notice', total_quantity=None,
                      total_quantity_scale=None, total_quantity_decimals=None, total_ratio=None)
        assert validate(kind, STOCK['unified_code'], [report])


@pytest.mark.parametrize('kind', KINDS)
def test_quantity_exit_identity_and_optional_cells(kind):
    reports = parse(source(pledge=True, malformed=True), kind, STOCK)
    report = reports[0]
    assert report['total_quantity'] == '1000000' and len(report['members']) == 11
    assert report['members'][0]['quantity'] == '100000'
    assert report['members'][-1]['member_group'] == 'exited'
    if kind != 'bond_holders':
        assert report['members'][0]['change_quantity'] == '-10000'
        assert report['members'][0]['share_type'] == '流通A股'
        assert report['members'][0]['pledge_status'] == '无质押'


@pytest.mark.parametrize('damage', ['identity', 'truncated', 'missing_panel', 'duplicate', 'unit', 'unknown_column'])
def test_source_damage_is_not_empty_or_complete(damage):
    body = source()
    if damage == 'identity':
        body = body.replace('value="601139"', 'value="601138"')
    elif damage == 'truncated':
        body = body[:-7]
    elif damage == 'missing_panel':
        body = body.replace('id="tenholder_1"', 'id="wrong"')
    elif damage == 'duplicate':
        body = body.replace('股东1', '股东0')
    elif damage == 'missing_row':
        body = source(count=9)
    elif damage == 'unit':
        body = body.replace('持有数量(股)', '持有数量(万股)')
    else:
        body = body.replace('股份类型', '新未知列')
    with pytest.raises(ValueError):
        parse(body, 'top_holders', STOCK)


def test_absent_bond_is_source_not_published_and_corrupt_page_fails():
    assert parse(source(bond=False), 'bond_holders', STOCK) == []
    with pytest.raises(ValueError):
        parse('<html><input id="stockCode" value="601139"></html>', 'bond_holders', STOCK)


def test_precision_date_and_same_count_wrong_business_set():
    reports = parse(source(), 'top_holders', STOCK)
    bad = copy.deepcopy(reports)
    bad[0]['members'][1]['holder_name'] = bad[0]['members'][0]['holder_name']
    with pytest.raises(ValueError):
        validate('top_holders', STOCK['unified_code'], bad)
    with pytest.raises(ValueError):
        parse(source().replace('10.00万', '10.00001万'), 'top_holders', STOCK)


def test_change_notice_is_partial_with_unknown_total_and_bond_rank_gap_preserved():
    body = source(count=3).replace('<caption>前十大累计持有：<em>100.00万股</em>，累计占总股本比：<em>10.00%</em></caption>',
                                '<caption>主要股东持股变动公告</caption>')
    report = parse(body, 'top_holders', STOCK)[0]
    assert report['report_type'] == 'change_notice' and report['total_quantity'] is None
    assert len([m for m in report['members'] if m['member_group'] == 'current']) == 3
    report = parse(source(), 'bond_holders', STOCK)[0]
    report['members'] = [m for m in report['members'] if m['member_group'] != 'current' or m['seq'] != 7]
    report['total_quantity'], report['total_ratio'] = '900000', '9'
    for i, m in enumerate([m for m in report['members'] if m['member_group'] == 'current'], 1):
        m['seq'] = i
    assert [m['source_rank'] for m in report['members'] if m['member_group'] == 'current'] == [1,2,3,4,5,6,8,9,10]
    validate('bond_holders', STOCK['unified_code'], [report])


def test_multiple_bonds_and_same_date_notice_have_distinct_identity():
    from empire.features.holders.contract import report_key
    body = source()
    start = body.index('<div id="bondholder">')
    block = body[start + len('<div id="bondholder">'):-len('</div></html>')]
    second = block.replace('燃23转债', '燃24转债').replace('bondholder_1', 'bondholder_2')
    body = body[:start] + '<div id="bondholder">' + block + second + '</div></html>'
    rows = parse(body, 'bond_holders', STOCK)
    assert {r['instrument_name'] for r in rows} == {'燃23转债', '燃24转债'}
    assert len({report_key(r) for r in rows}) == 2
    periodic = parse(source(), 'top_holders', STOCK)[0]
    notice = copy.deepcopy(periodic)
    notice.update(report_type='change_notice', total_quantity=None, total_quantity_scale=None,
                  total_quantity_decimals=None, total_ratio=None)
    assert report_key(periodic) != report_key(notice)
    validate('top_holders', STOCK['unified_code'], [periodic, notice])


def test_bond_exit_rank_order_has_one_canonical_sql_representation():
    body = source()
    exit_row = '<tr class="gray"><td>4</td><td>退出人</td><td>5</td><td>0.50</td></tr>'
    second = exit_row.replace('<td>4</td>', '<td>2</td>').replace('退出人', '另一退出人')
    body = body.replace(exit_row, exit_row + second)
    report = parse(body, 'bond_holders', STOCK)[0]
    assert [m['source_rank'] for m in report['members'] if m['member_group'] == 'exited'] == [4, 2]
    assert [m['seq'] for m in report['members'] if m['member_group'] == 'exited'] == [1, 2]
    bad = copy.deepcopy(report)
    bad['members'][-2:] = reversed(bad['members'][-2:])
    with pytest.raises(ValueError):
        validate('bond_holders', STOCK['unified_code'], [bad])


@pytest.mark.parametrize('kind', KINDS)
def test_cell_quantity_unit_must_match_business_kind(kind):
    body = source().replace('<td>10.00</td>', '<td>10.00万股</td>') if kind == 'bond_holders' else source().replace('<td>10.00万</td>', '<td>10.00万张</td>')
    with pytest.raises(ValueError):
        parse(body, kind, STOCK)


def test_explicit_bond_base_unit_overrides_header_display_scale():
    report = parse(source().replace('<td>10.00</td>', '<td>100000张</td>'), 'bond_holders', STOCK)[0]
    assert report['members'][0]['quantity'] == '100000'
    assert report['members'][0]['quantity_scale'] == 1


def configured(stocks=None):
    c = HolderCollector()
    c.ingest = Publisher()
    c.query = SimpleNamespace(securities=AsyncMock(return_value=stocks or [STOCK]))
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.session = SimpleNamespace(headers=lambda _: {})
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw:
        httpx.Response(200, content=source(url.split('/')[-2]).encode('gb18030'))))
    return c


async def test_one_request_all_three_sections_and_no_wait_between_securities():
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    c = configured(stocks)
    gate = asyncio.Event()
    async def confirm(*args):
        assert c.http.request.await_count == 2
        await gate.wait()
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while c.stats['status'] != 'awaiting_archive':
            await asyncio.sleep(0)
    assert (await c.ingest.checkpoint(c.job_key))['cursor']['index'] == 2
    assert len(c.ingest.events) == 3
    assert set(c.ingest.events[0].raw_payload['reports']) == set(KINDS)
    gate.set()
    result = await task
    assert result['phase'] == 'complete' and c.http.request.await_count == 2
    assert result['scope_hash'] == digest([s['unified_code'] for s in stocks])


async def test_validation_failure_checkpoint_and_recovery():
    c = configured()
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, content=source(code='000000').encode('gb18030'))
    with pytest.raises(ValueError):
        await c.execute()
    assert (await c.ingest.checkpoint(c.job_key))['revision'] == 0
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, content=source().encode('gb18030'))
    assert (await c.execute())['phase'] == 'complete'


async def test_expanded_source_summary_mismatch_preserves_original_with_quality():
    c = configured()
    body = source(expanded=True).replace('109.00万股', '100.00万股')
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, content=body.encode('gb18030'))
    assert (await c.execute())['phase'] == 'complete'
    rows = c.ingest.events[0].raw_payload['reports']['top_holders']
    assert rows[0]['quality_flags'] == 2 and rows[0]['total_quantity'] == '1000000'
    assert len(rows[0]['members']) == 12


async def test_source_gap_admits_next_security_and_cancel_drains_prefetch():
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'},
              {**STOCK, 'code': '601141', 'unified_code': '601141.SH'}]
    c = configured(stocks=stocks)
    c.http.parallelism.return_value = 3
    finished = asyncio.Event()
    cancelled = asyncio.Event()
    async def fetch(method, url, **kw):
        code = url.split('/')[-2]
        if code == '601140':
            finished.set()
            return httpx.Response(200, content=source(code).encode('gb18030'))
        if code == '601141':
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        await finished.wait()
        return httpx.Response(200, content=source('000000').encode('gb18030'))
    c.http.request.side_effect = fetch
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while not c.ingest.events:
            await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(c.ingest.events) == 1 and c.ingest.events[0].raw_payload['unit'] == '601140.SH'
    assert (await c.ingest.checkpoint(c.job_key))['cursor']['index'] == 0
    assert cancelled.is_set() and c.http.buffer_budget.used == 0


async def test_source_gap_continues_to_end_confirms_once_and_resumes_first_gap():
    stocks = [{**STOCK, 'code': str(601139+i), 'unified_code': str(601139+i)+'.SH'} for i in range(4)]
    c = configured(stocks)
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200,
        content=source('000000' if url.split('/')[-2] == '601140' else url.split('/')[-2]).encode('gb18030'))
    async def confirm(*args):
        assert c.http.request.await_count == 4
        assert [e.raw_payload['unit'] for e in c.ingest.events] == ['601139.SH', '601141.SH', '601142.SH']
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    with pytest.raises(ValueError, match='1只证券来源校验失败'):
        await c.execute()
    cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
    assert cursor['index'] == 1 and cursor['collected'] == 3 and cursor['pages'] == 3
    assert c.stats['processed_units'] == 4 and c.stats['failed_units'] == 1
    assert c.stats['continuous_collected'] == 3 and c.stats['collected'] == 9
    assert c.records.add_error.await_count == 1 and c.confirmation.page_status.await_count == 1
    previous_batch = cursor['batch_id']
    c.confirmation.page_status.side_effect = None
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200,
        content=source(url.split('/')[-2]).encode('gb18030'))
    result = await c.execute(baseline_revision=await c.checkpoint_revision())
    assert result['phase'] == 'complete' and result['index'] == 4
    assert result['batch_id'] != previous_batch and result['pages'] == 4
    assert result['collected'] == 12 and c.http.request.await_count == 7
    assert c.ingest.events[-1].raw_payload['manifest']['securities'] == [s['unified_code'] for s in stocks]


async def test_scope_change_restarts_download_and_cancel_keeps_enqueued_boundary():
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    c = configured(stocks=stocks)
    original = c.ingest.publish_page
    async def interrupted(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError
    c.ingest.publish_page = interrupted
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert c.ingest.state['cursor']['index'] == 1
    c.ingest.publish_page = original
    c.query.securities.return_value = stocks + [{**STOCK, 'code': '601141', 'unified_code': '601141.SH'}]
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.stats['scope_changed'] and c.http.request.await_count == 4
    assert c.http.buffer_budget.used == 0


async def test_multiple_source_gaps_repeat_with_bounded_pages_and_no_manifest():
    stocks = [{**STOCK, 'code': str(601139+i), 'unified_code': str(601139+i)+'.SH'} for i in range(3)]
    c = configured(stocks)
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200,
        content=source(url.split('/')[-2] if url.split('/')[-2] == '601140' else '000000').encode('gb18030'))
    batches = set()
    for _ in range(3):
        with pytest.raises(ValueError, match='2只证券来源校验失败'):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
        assert cursor['index'] == 0 and cursor['collected'] == 0 and cursor['pages'] == 1
        batches.add(cursor['batch_id'])
        assert c.stats['processed_units'] == 3 and c.stats['failed_units'] == 2
    assert len(batches) == 3 and c.http.request.await_count == 9
    assert all(e.raw_payload['manifest'] is None for e in c.ingest.events)


async def test_all_source_gaps_leave_checkpoint_unchanged():
    c = configured([STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}])
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200,
        content=source('000000').encode('gb18030'))
    with pytest.raises(ValueError, match='2只证券来源校验失败'):
        await c.execute()
    assert c.http.request.await_count == 2 and not c.ingest.events
    assert (await c.ingest.checkpoint(c.job_key))['revision'] == 0
    c.confirmation.page_status.assert_not_awaited()


async def test_local_request_failure_stops_instead_of_becoming_source_gap():
    c = configured([STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}])
    c.http.request.side_effect = ValueError('invalid local response budget')
    with pytest.raises(ValueError, match='invalid local response budget'):
        await c.execute()
    assert not c.ingest.events and c.stats['failed_units'] == 0


def test_one_collector_task_and_three_independent_pages():
    m = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    control = m.entries['collection.control'].plugin
    for kind in KINDS:
        from empire.features.holders.contract import project
        task = control.definitions[project(kind)]
        assert task.default_schedule.mode == 'daily' and task.parallel_downloads
        assert 'collector.ths_holders' in m.entries and 'ui.' + kind in m.entries
        assert 'collector.ths_' + kind not in m.entries
    assert sum(k.startswith('ths-') and 'holder' in k for k in control.definitions) == 1
