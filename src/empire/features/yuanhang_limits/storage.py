"""Canonical typed payloads; repeat validation at the archive trust boundary."""
from empire.contracts.security import split_unified_code
from empire.features.yuanhang_limits.contract import (
    FILTER,
    MARKETS,
    MAX_MEMBERS,
    MEMBER_FIELDS,
    POOL_FILTER_VERSIONS,
    TIME_FIELDS,
    day_value,
    pool_value,
)
from empire.features.yuanhang_limits.model import digest, member, parse_reason


def validate_member(value, day):
    if not isinstance(value, dict) or set(value) != set(MEMBER_FIELDS):
        raise ValueError('池成员规范字段不符')
    market, code = split_unified_code(value['unified_code'])
    ids = {v: k for k, v in MARKETS.items()}
    if market not in ids:
        raise ValueError('不支持的池成员市场')
    raw = {k: v for k, v in value.items() if k not in ('unified_code', 'top_concept', 'source_market_id', 'identity_basis')}
    raw.update(code=code, market_id=value['source_market_id'], **{'941948930': value['top_concept']})
    for key in TIME_FIELDS:
        if raw[key] is not None:
            if type(raw[key]) is not int:
                raise ValueError('池成员规范时间非整数')
            raw[key] = str(raw[key])
    identities = ({code: (value['unified_code'], value['identity_basis'])}
                  if value['identity_basis'] in ('pool_history', 'sina_lookup') else None)
    result = member(raw, day, identities=identities)
    if result != value:
        raise ValueError('池成员未使用规范数值表示')
    return result


def pool_payload(value, *, require_current=True):
    if not isinstance(value, dict) or set(value) != {'trade_date', 'pool_type', 'filter', 'source_total', 'rows'}:
        raise ValueError('日期池规范字段不符')
    day = day_value(value['trade_date'])
    pool_value(value['pool_type'])
    rows = value['rows']
    filters = (FILTER,) if require_current else POOL_FILTER_VERSIONS
    if (value['filter'] not in filters or type(value['source_total']) is not int or not isinstance(rows, list)
            or not 0 <= len(rows) <= MAX_MEMBERS or value['source_total'] != len(rows)):
        raise ValueError('日期池过滤或完整集合计数不符')
    normalized = [validate_member(row, day) for row in rows]
    keys = [row['unified_code'] for row in normalized]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError('日期池身份重复或未规范排序')
    return {**value, 'rows': normalized}


def reason_payload(value):
    fields = {'unified_code', 'trade_date', 'name', 'reason_text', 'reason_kind', 'availability'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('证券日原因规范字段不符')
    data = {}
    for origin, target in (('reasonrevealedList', 'reason_text'), ('reasonKindList', 'reason_kind')):
        data[origin] = (None if value['name'] is None else
                        [{'valueList': [value['unified_code'], value['name'], value[target]]}])
        if value['name'] is None and value[target] is not None:
            raise ValueError('原因正文缺少证券名称')
    result = parse_reason({'status_code': 0, 'data': data}, value['unified_code'], value['trade_date'])
    if result != value:
        raise ValueError('原因可用性或规范内容不符')
    return result


def pool_proof(value):
    return {'source_total': value['source_total'], 'filter_text': value['filter'],
            'key_sha256': digest([r['unified_code'] for r in value['rows']]),
            'content_sha256': digest(value), 'contract_version': POOL_FILTER_VERSIONS[value['filter']]}
