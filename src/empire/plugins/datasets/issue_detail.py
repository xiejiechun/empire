"""TDX additional-issue detail contract, including nullable historical fields."""
from datetime import datetime

from empire.plugins.datasets.capital_actions import TdxSourceError, day, number

COLUMNS = ['T048', 'T049', 'code', 'name', 'T012', 'fxfs', 'fxrq', 'T044', 'T055',
           'T057', 'T080', 'T005', 'T037', 'T026', 'T102', 'T052', 'T039', 'T040',
           'T104', 'T024', 'cT012', 'T111', 'T109', 'T017', 'OpenPrice', 'ClosePrice', 'kpzdf', 'spzdf']
TEXT = {'T049': 'subscription_name', 'cT012': 'lead_underwriter', 'T111': 'underwriting_method',
        'T109': 'issue_targets', 'T017': 'pricing_method'}
NUMBERS = {'T055': ('online_shares', 10000), 'T057': ('offline_shares', 10000),
           'T026': ('gross_proceeds', 10000), 'T052': ('online_winning_percent', 1),
           'T104': ('post_issue_eps', 1), 'T024': ('post_issue_net_assets', 1),
           'OpenPrice': ('first_day_open', 1), 'ClosePrice': ('first_day_close', 1),
           'kpzdf': ('first_day_open_change_percent', 1), 'spzdf': ('first_day_close_change_percent', 1)}
SIGNED = {'T104', 'T024', 'kpzdf', 'spzdf'}


class IssueSourceError(TdxSourceError):
    """The endpoint returned a readable business failure, not a transport outage."""

    def __init__(self, code):
        super().__init__(code, '增发详情')


def normalize(raw):
    result = {}
    for field, key in TEXT.items():
        value = raw[field]
        if value is not None and (not isinstance(value, str) or len(value) > 60000):
            raise ValueError('增发详情文本无效或过长')
        result[key] = value.strip() or None if value is not None else None
    for field, (key, scale) in NUMBERS.items():
        result[key] = number(raw[field], scale, signed=field in SIGNED)
    result['online_allotment_date'] = day(raw['T044'])
    value = raw['T102']
    if value in (None, ''):
        value = None
    elif isinstance(value, str) and len(value) == 19:
        if datetime.fromisoformat(value).strftime('%Y-%m-%d %H:%M:%S') != value or value[10:] != ' 00:00:00':
            raise ValueError('增发中签公告日期格式无效')
        value = value[:10]
    result['winning_announcement_date'] = day(value)
    return result


def validate(detail):
    if not isinstance(detail, dict):
        raise ValueError('增发详情尚未补齐')
    if detail.get('availability') == 'unavailable':
        if (set(detail) not in ({'availability', 'source_error_code'},
                               {'availability', 'source_error_code', 'last_available'})
                or type(detail['source_error_code']) is not int or detail['source_error_code'] not in (0, -1005)):
            raise ValueError('来源暂无详情状态无效')
        if 'last_available' in detail:
            if not isinstance(detail['last_available'], dict) or 'availability' in detail['last_available']:
                raise ValueError('上次有效详情无效')
            validate(detail['last_available'])
        return detail
    raw = {field: detail[key] for field, key in TEXT.items()}
    from decimal import Decimal
    raw.update({field: None if detail[key] is None else str(Decimal(detail[key]) / scale)
                for field, (key, scale) in NUMBERS.items()})
    raw.update(T044=detail['online_allotment_date'], T102=detail['winning_announcement_date'])
    if normalize(raw) != detail:
        raise ValueError('增发详情未按正式契约规范化')
    return detail


def parse(body, row, aliases):
    if isinstance(body, dict) and type(body.get('ErrorCode')) is int and body['ErrorCode'] == -1005:
        return {'availability': 'unavailable', 'source_error_code': -1005}
    if isinstance(body, dict) and type(body.get('ErrorCode')) is int and body['ErrorCode'] != 0:
        raise IssueSourceError(body['ErrorCode'])
    if not isinstance(body, dict) or body.get('ErrorCode') != 0:
        raise ValueError('增发详情请求失败')
    sets = body.get('ResultSets')
    if not isinstance(sets, list) or len(sets) != 1:
        raise ValueError('增发详情结果集缺失')
    table = sets[0]
    if (isinstance(table, dict) and table.get('ColName') == COLUMNS
            and type(table.get('Count')) is int and table['Count'] == 0 and table.get('Content') == []):
        return {'availability': 'unavailable', 'source_error_code': 0}
    if (not isinstance(table, dict) or table.get('ColName') != COLUMNS
            or type(table.get('Count')) is not int or table['Count'] != 1
            or not isinstance(table.get('Content'), list) or len(table['Content']) != 1
            or not isinstance(table['Content'][0], list) or len(table['Content'][0]) != len(COLUMNS)):
        raise ValueError('增发详情必须返回完整的一条方案')
    raw = dict(zip(COLUMNS, table['Content'][0], strict=True))
    if raw['code'] not in aliases or not isinstance(raw['name'], str) or not raw['name'].strip():
        raise ValueError('增发详情证券关联不匹配')
    d = row['data']
    shared = dict(subscription_code=raw['T048'] or None, issue_method=raw['fxfs'],
        issue_price=number(raw['T012']), issue_date=day(raw['fxrq']), listing_date=day(raw['T080']),
        issued_shares=number(raw['T005'], 10000, required=True), record_date=day(raw['T037']),
        shares_before=number(raw['T039'], 10000), shares_after=number(raw['T040'], 10000))
    if any(d[key] != value for key, value in shared.items()):
        raise ValueError('增发列表与详情方案内容不一致；保留断点待复核')
    return normalize(raw)
