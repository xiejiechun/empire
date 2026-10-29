import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import (
    DECIMAL_FIELDS,
    INTEGER_FIELDS,
    TEXT_LIMITS,
    TIME_FIELDS,
)
from empire.features.yuanhang_limits.model import member, parse_page, parse_reason
from empire.features.yuanhang_limits.source import fetch_pool, fetch_reason


def row(code='000001'):
    return {**dict.fromkeys(DECIMAL_FIELDS), **dict.fromkeys(INTEGER_FIELDS),
            **dict.fromkeys(TEXT_LIMITS), **dict.fromkeys(TIME_FIELDS),
            'code': code, 'market_id': 33, 'market_type': 'HS', 'name': '样本',
            'latest': 10.15, 'change_rate': 9.9999, 'order_volume': 0,
            'first_limit_up_time': str(int(datetime(2026, 7, 15, 9, 30, tzinfo=CHINA).timestamp()))}


def page(rows, total=None, number=1):
    total = len(rows) if total is None else total
    return {'status_code': 0, 'data': {'data': rows, 'page': {
        'total': total, 'count': (total + 99) // 100, 'limit': 100, 'page': number if total else 0}}}


def test_units_nulls_and_identity_are_preserved():
    value = member(row(), '2026-07-15')
    assert value['unified_code'] == '000001.SZ'
    assert value['latest'] == '10.15' and value['change_rate'] == '9.9999'
    assert value['order_volume'] == '0' and value['order_amount'] is None
    assert value['high_days'] is None


def test_decimal_precision_is_not_lost_to_default_decimal_context():
    from empire.features.yuanhang_limits.model import decimal_value
    source = '12345678901234567890.123456789012345678901234'
    assert decimal_value(source, 'turnover') == source


@pytest.mark.parametrize('field,value', [('market_id', 34), ('market_id', True),
    ('latest', float('nan')), ('latest', '1.0000000000000000000000001'), ('latest', -1), ('is_new', 3),
    ('limit_up_suc_rate', 50), ('first_limit_up_time', '1783992705')])
def test_invalid_fields_fail(field, value):
    data = row()
    data[field] = value
    with pytest.raises(ValueError):
        member(data, '2026-07-15')


def test_missing_field_is_not_source_null():
    value = row()
    del value['reason_type']
    with pytest.raises(ValueError):
        member(value, '2026-07-15')


def test_historical_risk_market_and_explicit_growth_board_identity():
    assert member({**row('871478'), 'market_id': 151}, '2026-07-15')['unified_code'] == '871478.BJ'
    risk = {**row('600157'), 'market_id': 22}
    assert member(risk, '2026-07-15')['unified_code'] == '600157.SH'
    missing = {**row('300362'), 'market_id': None, 'market_type': 'GEM'}
    parsed = member(missing, '2026-07-15')
    assert parsed['unified_code'] == '300362.SZ'
    assert parsed['source_market_id'] is None and parsed['identity_basis'] == 'source_board'
    with pytest.raises(ValueError):
        member({**missing, 'market_type': 'HS'}, '2026-07-15')
    with pytest.raises(ValueError):
        member({**missing, 'market_id': 17}, '2026-07-15')


def test_equal_count_duplicate_missing_identity_and_page_errors():
    with pytest.raises(ValueError):
        parse_page(page([row(), row()]), '2026-07-15', 1)
    for obj in [page([row()], total=2), page([row()], number=2), {'status_code': -1}]:
        with pytest.raises(ValueError):
            parse_page(obj, '2026-07-15', 1)
    assert parse_page(page([]), '2026-07-15', 1) == ([], 0, 0)


def test_zero_time_and_proven_history_identity_round_trip():
    from empire.features.yuanhang_limits.storage import validate_member
    raw = {**row('300362'), 'market_id': None, 'first_limit_up_time': '0'}
    parsed = member(raw, '2026-07-15', identities={'300362': '300362.SZ'})
    assert parsed['identity_basis'] == 'pool_history'
    assert parsed['first_limit_up_time'] == 0
    assert validate_member(parsed, '2026-07-15') == parsed
    with pytest.raises(ValueError):
        member(raw, '2026-07-15', identities={'300362': '300363.SZ'})
    with pytest.raises(ValueError):
        member({**raw, 'market_id': 34}, '2026-07-15', identities={'300362': '300362.SZ'})


@pytest.mark.asyncio
async def test_missing_identity_uses_one_bounded_lookup_without_redownload():
    http, responses = client(page([{**row('300362'), 'market_id': None}]))
    resolve = AsyncMock(return_value={'300362': '300362.SZ'})
    value = await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test', identity_resolver=resolve)
    assert value['rows'][0]['identity_basis'] == 'pool_history'
    resolve.assert_awaited_once_with({'300362'})
    assert http.request.call_count == 1
    responses[0].close.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_history_identity_uses_exact_supplement_and_accounts_cost():
    http, responses = client(page([{**row('600687'), 'market_id': None}]))
    body = b'var themeIdentity="old,11,600687,sh600687,old,,old,99,0,,,old";'
    responses.append(SimpleNamespace(content=body, close=Mock()))
    http.request.side_effect = responses
    value = await fetch_pool(http, 'limit_down_pool', '2026-07-15', project_id='test',
                             identity_resolver=AsyncMock(return_value={}))
    assert value['rows'][0]['unified_code'] == '600687.SH'
    assert value['rows'][0]['identity_basis'] == 'sina_lookup'
    assert value['requests'] == http.request.call_count == 2
    assert value['response_bytes'] == sum(len(r.content) for r in responses)
    assert all(r.close.call_count == 1 for r in responses)


def detail(value='正文'):
    return {'status_code': 0, 'data': {'reasonrevealedList': [{'valueList': ['000001.SZ', '样本', value]}],
                                      'reasonKindList': None}}


def test_reason_single_day_null_and_sparse_range_rejection():
    assert parse_reason(detail(), '000001.SZ', '2026-07-15')['reason_text'] == '正文'
    assert parse_reason(detail(None), '000001.SZ', '2026-07-15')['availability'] == 'no_content'
    obj = detail()
    obj['data']['reasonrevealedList'][0]['valueList'].append('无日期标签的下一篇')
    with pytest.raises(ValueError):
        parse_reason(obj, '000001.SZ', '2026-07-15')
    obj = detail()
    obj['data']['reasonrevealedList'][0]['valueList'][0] = '000002.SZ'
    with pytest.raises(ValueError):
        parse_reason(obj, '000001.SZ', '2026-07-15')


@pytest.mark.parametrize('empty_column', ['reasonrevealedList', 'reasonKindList'])
def test_reason_empty_array_is_an_independently_unavailable_column(empty_column):
    obj = detail()
    obj['data']['reasonKindList'] = [{'valueList': ['000001.SZ', '样本', '分类']}]
    obj['data'][empty_column] = []
    result = parse_reason(obj, '000001.SZ', '2026-07-15')
    assert result['name'] == '样本' and result['availability'] == 'available'
    assert result['reason_text'] == (None if empty_column == 'reasonrevealedList' else '正文')
    assert result['reason_kind'] == (None if empty_column == 'reasonKindList' else '分类')
    obj['data'] = dict(reasonrevealedList=[], reasonKindList=[])
    result = parse_reason(obj, '000001.SZ', '2026-07-15')
    assert result['name'] is None and result['availability'] == 'no_content'
    obj = detail()
    obj['data']['reasonrevealedList'] *= 2
    with pytest.raises(ValueError, match='单证券行数'):
        parse_reason(obj, '000001.SZ', '2026-07-15')


def test_reason_documented_code_change_preserves_historical_query_identity():
    obj = detail('历史正文')
    obj['data']['reasonrevealedList'][0]['valueList'][:2] = ['302132.SZ', '中航成飞']
    value = parse_reason(obj, '300114.SZ', '2020-08-03')
    assert value['unified_code'] == '300114.SZ'
    assert value['name'] == '中航成飞' and value['reason_text'] == '历史正文'
    for code, day in [('300114.SZ', '2025-02-17'), ('300115.SZ', '2020-08-03')]:
        with pytest.raises(ValueError, match='身份或日期槽'):
            parse_reason(obj, code, day)


def client(*objects, budget=8 * 1024 * 1024):
    responses = [SimpleNamespace(content=json.dumps(obj).encode(), close=Mock()) for obj in objects]
    http = SimpleNamespace(request=AsyncMock(side_effect=responses),
                           response_policy=Mock(return_value=SimpleNamespace(max_body_bytes=budget)))
    return http, responses


@pytest.mark.asyncio
async def test_normal_pagination_one_request_per_page_and_shared_policy():
    first = [row(f'{i:06}') for i in range(1, 101)]
    http, responses = client(page(first, 101), page([row('000101')], 101, 2))
    result = await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test')
    assert len(result['rows']) == 101 and result['requests'] == 2
    assert http.request.call_count == 2
    for call in http.request.call_args_list:
        assert 'orderField=code' in call.args[1] and 'orderType=1' in call.args[1]
        assert call.kwargs['allowed_domains'] == ('10jqka.com.cn',)
    assert all(r.close.call_count == 1 for r in responses)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['reorder', 'total', 'budget'])
async def test_failed_complete_unit_cannot_return_partial_members(failure):
    first = [row(f'{i:06}') for i in range(1, 101)]
    tail = row('000100' if failure == 'reorder' else '000101')
    http, responses = client(page(first, 101), page([tail], 102 if failure == 'total' else 101, 2),
                             budget=100 if failure == 'budget' else 8 * 1024 * 1024)
    with pytest.raises(ValueError):
        await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test')
    assert responses[0].close.call_count == 1


@pytest.mark.asyncio
async def test_reason_only_requests_single_date_and_closes_response():
    http, responses = client(detail())
    result = await fetch_reason(http, '000001.SZ', '2026-07-15', project_id='test')
    assert result['reason_text'] == '正文'
    assert 'startTime=20260715&endTime=20260715' in http.request.call_args.args[1]
    responses[0].close.assert_called_once()


async def test_reason_failure_keeps_source_identity_body_and_business_status():
    import httpx
    url = 'http://dq.10jqka.com.cn/failure'
    response = httpx.Response(200, request=httpx.Request('GET', url),
        json={'status_code': -17, 'status_msg': 'unavailable'})
    http = SimpleNamespace(request=AsyncMock(return_value=response), response_policy=lambda _: None)
    with pytest.raises(ValueError) as caught:
        await fetch_reason(http, '300010.SZ', '2020-03-23', project_id='ths-yuanhang-reason')
    assert caught.value.source_metadata == dict(business_status=-17, unified_code='300010.SZ', trade_date='2020-03-23')
    assert caught.value.source_diagnostic['raw_body'] == response.content
    assert response.is_closed
