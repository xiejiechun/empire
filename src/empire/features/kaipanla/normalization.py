"""Business-owned normalization; moved declarations retain existing behavior."""
from datetime import date, datetime

from empire.contracts.security import unified_code
from empire.core.time import CHINA
from empire.features.kaipanla.canonical import digest as hash_value
from empire.features.kaipanla.contract import PRODUCTS
from empire.features.kaipanla.parser import parse

FIELDS = {'kind', 'code', 'market', 'trade_date', 'source_code', 'aliases', 'data', 'lifecycle', 'metadata'}


def business_content(row):
    # Source calculation/observation clocks have no proven revision semantics.
    # They remain available as metadata, without causing repeated business DML.
    return {k: v for k, v in row.items() if k != 'metadata'}


def digest(row):
    return hash_value(business_content(row))


def validate(row, kind=None, *, storage_check=True):
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise ValueError('证券日字段不完整')
    item = PRODUCTS.get(row['kind'])
    if item is None or kind is not None and kind != row['kind']:
        raise ValueError('证券日数据类型错配')
    unified_code(row['market'], row['code'])
    day = date.fromisoformat(row['trade_date'])
    if day.isoformat() != row['trade_date'] or not date(2021, 1, 1) <= day <= datetime.now(CHINA).date():
        raise ValueError('日期超出支持范围')
    life = row['lifecycle']
    if (not isinstance(life, dict) or set(life) != {'listing_date', 'listing_source', 'market_start'}
            or life['listing_source'] != 'eastmoney'
            or day < max(date.fromisoformat(life['listing_date']), date.fromisoformat(life['market_start']))):
        raise ValueError('上市生命周期无效')
    if not isinstance(row['data'], dict) or not isinstance(row['aliases'], dict):
        raise ValueError('业务内容或映射证明无效')
    expected_alias = {row['source_code']} - {row['code'], None}
    if set(row['aliases']) != expected_alias:
        raise ValueError('来源代码映射关联错误')
    for proof in row['aliases'].values():
        if row['market'] != 'BJ' or proof['listing_date'] != life['listing_date']:
            raise ValueError('旧代码市场或上市日期错配')
    if not isinstance(row['metadata'], dict) or set(row['metadata']) - {'time', 'time2', 'ts'}:
        raise ValueError('来源元数据无效')
    payload = {**row['data'], **row['metadata'], 'errcode': '0', 'day': day.strftime('%Y%m%d')}
    if row['source_code'] is not None:
        payload['code'] = row['source_code']
    parsed = parse(payload, row['code'], day, row['kind'], row['aliases'])
    if parsed['data'] != row['data']:
        raise ValueError('业务数据未按现行契约规范化')
    from empire.features.kaipanla.codec import encode
    if storage_check:
        encode(row, '', datetime.now(CHINA).replace(tzinfo=None))
    return row


def point_count(row):
    field = PRODUCTS[row['kind']].field
    return len(row['data'][field]) if field else 1
