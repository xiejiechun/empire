from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang_limits.contract import TIME_FIELDS
from empire.features.yuanhang_limits.intraday_query import browse_live
from empire.features.yuanhang_limits.snapshot_order import snapshot_page


def members():
    return [dict(unified_code=f'{i:06}.SZ', latest=None if i % 9 == 0 else
                 f'900719925474099.{i % 7:06}', **dict.fromkeys(TIME_FIELDS)) for i in range(421)]


def test_complete_snapshot_decimal_ties_nulls_and_version_binding():
    rows = members()
    filters, order = [3, 'limit_up_pool', '', '2026-10-29', '', ''], dict(field='latest', direction='desc')
    result, cursor = [], None
    while True:
        page, cursor = snapshot_page(rows, 'v1', filters, order, cursor)
        result.extend(page)
        if cursor is None:
            break
    assert len(result) == len({r['unified_code'] for r in result}) == len(rows)
    assert [r['latest'] for r in result if r['latest']] == sorted(
        [r['latest'] for r in rows if r['latest']], reverse=True)
    assert all(r['latest'] is None for r in result[-47:])
    _, cursor = snapshot_page(rows, 'v1', filters, order, None)
    for version, selected_order in [('v2', order), ('v1', dict(field='latest', direction='asc'))]:
        with pytest.raises(ValueError, match='快照或筛选'):
            snapshot_page(rows, version, filters, selected_order, cursor)


async def test_formal_live_query_keeps_snapshot_and_reports_expiration(monkeypatch):
    stamp = '2026-10-29T10:00:00+08:00'
    read = AsyncMock(return_value=dict(
        unit=dict(rows=members(), source_total=421), version='1793239200000000',
        started=stamp, finished=stamp, meta=dict(checked='1793239200000000'),
        retained_since=None, consistency='single_response',
    ))
    monkeypatch.setattr('empire.features.yuanhang_limits.intraday_query.IntradayStore',
                        lambda _: SimpleNamespace(read=read))
    query = SimpleNamespace(context=SimpleNamespace(optional=lambda _: object()))
    filters, order = [3, 'limit_up_pool', '', '2026-10-29', '', ''], dict(field='latest', direction='asc')
    first = await browse_live(query, filters, None, order)
    second = await browse_live(query, filters, first['next'], order)
    assert read.call_args.kwargs['version'] == '1793239200000000'
    assert not {r['unified_code'] for r in first['rows']} & {r['unified_code'] for r in second['rows']}
    read.return_value = None
    with pytest.raises(ValueError, match='快照已失效'):
        await browse_live(query, filters, second['next'], order)
