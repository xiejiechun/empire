from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from empire.features.themes.detail_model import DetailError, parse_detail
from empire.features.themes.history_model import digest
from empire.features.themes.storage_contract import (
    binary32,
    daily_record,
    decode_daily,
    detail_version,
    epoch,
    list_rows,
    map_detail,
    security_map,
    source_time,
    validate_detail,
)
from tests.test_theme_detail_source import sample


def mapped():
    return map_detail(parse_detail(sample(), '148'), ['600001.SH'])


def test_full_detail_mapping_preserves_source_and_relations():
    value = mapped()
    assert validate_detail(value) == value
    assert value['stocks'][0]['unified_code'] == '600001.SH'
    assert value['relations'][0]['source_stock_id'] == '600001'
    assert security_map(['600001.SH', '600001.SH']) == {'600001': '600001.SH'}
    with pytest.raises(DetailError, match='多个市场'):
        security_map(['600001.SH', '600001.SZ'])
    with pytest.raises(DetailError, match='缺少'):
        map_detail(parse_detail(sample(), '148'), [])


@pytest.mark.parametrize('mutation', [
    lambda v: v['stocks'][0].update(unified_code='600002.SH'),
    lambda v: v['stocks'].clear(),
    lambda v: v['relations'].clear(),
    lambda v: v['categories'][0].update(parent_id='7'),
    lambda v: v['categories'][0].update(order=3),
    lambda v: v['relations'][0].update(reason='篡改而未更新摘要'),
    lambda v: v['relations'][0].update(occurrences=0),
    lambda v: v.update(source_updated_at=True),
    lambda v: v.update(source_updated_at=999999999999),
    lambda v: v['stocks'][0].update(name='***'),
])
def test_queue_rejects_damaged_required_fields_and_equal_count_wrong_sets(mutation):
    value = deepcopy(mapped())
    mutation(value)
    with pytest.raises((DetailError, ValueError)):
        validate_detail(value)


def test_both_uncategorized_and_multiple_reason_grains_validate():
    raw = sample()
    raw['Stocks'] = raw['Table'][0]['Level1']['Stocks']
    raw['Table'] = []
    raw['StockList'][0]['Tag'] = []
    value = map_detail(parse_detail(raw, '148'), ['600001.SH'])
    assert validate_detail(value)['relations'][0]['category_id'] is None
    other = deepcopy(value['relations'][0])
    other['reason'] = '第二条原因'
    other['relation_id'] = digest({k: v for k, v in other.items() if k not in ('relation_id', 'occurrences')})
    value['relations'].append(other)
    assert len(validate_detail(value)['relations']) == 2


def test_timestamp_roundtrip_and_version_order():
    assert source_time(1703489277) == datetime(2023, 12, 25, 15, 27, 57)
    assert epoch(source_time(1703489277)) == 1703489277
    assert source_time(None) is None
    observed = datetime(2026, 10, 24, tzinfo=UTC)
    value = mapped()
    assert detail_version(value, observed)[1] == '2026-10-24T00:00:00.000000+00:00'


@pytest.mark.parametrize('number', [0.0, 1.8951416015625, -123.125, 1.401298464324817e-45])
def test_binary32_exact_decimal_survives_sql_value(number):
    from empire.features.themes.history_model import decimal_text
    value = decimal_text(Decimal.from_float(binary32(number)), 149, 12)
    row = dict(theme_id='148', source_theme_id='148', concept_id=None, name='军工', parent_id=None,
               new_flag=0, rank_no=6, display_order=5, hot_score='34200', change_rate=value, limit_up_count=1)
    rows = list_rows([row])
    assert decode_daily(daily_record(rows[0], '2026-10-24', datetime.now(UTC))) == row
    row['change_rate'] = '0.1'
    with pytest.raises(ValueError, match='binary32'):
        list_rows([row])
