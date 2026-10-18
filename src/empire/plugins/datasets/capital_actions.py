"""Canonical business contracts shared by three independent capital-action datasets."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation


class TdxSourceError(ValueError):
    """An explicit TDX business error must never be treated as a valid empty unit."""

    def __init__(self, code, operation):
        self.source_error_code = code
        info = '数据库执行失败' if code == -1005 else '源站业务错误'
        super().__init__(f'{operation}请求失败：通达信 ErrorCode={code}，{info}；数据未补齐')

KINDS = {
    'dividends': ('分红送转', 'dividend_plan', 'tdx-dividends'),
    'additional_issues': ('增发', 'additional_issue', 'tdx-additional-issues'),
    'rights_issues': ('配股', 'rights_issue', 'tdx-rights-issues'),
}
SCHEMA_VERSIONS = {'dividends': 3, 'additional_issues': 3, 'rights_issues': 1}
DIVIDEND_COLUMNS = ['fhbgq', 'T013', 'T014', 'szzs', 'T015', 'ygrq', 'gqdjr', 'cqcxr',
                    'fajd', 'T006', 'T010', 'T012', 'T009']
ISSUE_COLUMNS = ['sc', 'code', 'name', 'T097', 'T005', 'T039', 'T040', 'T048', 'T037',
                 'T012', 'ClosePrice', 'T043', 'T046', 'fxrq', 'T080', 'rec_id', 'fxfs']
RIGHTS_COLUMNS = ['sc', 'T005', 'T006', 'gqdjr', 'cqjzr', 'jqqsr', 'jqjzr', 'T015',
                  'T022', 'T023', 'T038', 'T043', 'code', 'name', 'price']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def security(market, code, name):
    if market not in ('SH', 'SZ', 'BJ') or not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        raise ValueError('增发送配证券市场或代码无效')
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('增发送配证券名称无效')
    return dict(market=market, code=code, name=name.strip())


def day(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('来源日期格式无效')
    if value < '1980-01-01':
        raise ValueError('来源日期超出支持范围')
    return value


def number(value, scale=1, *, required=False, signed=False):
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('来源数值无效')
    try:
        result = Decimal(str(value)) * Decimal(str(scale))
    except InvalidOperation:
        raise ValueError('来源数值无效') from None
    if not result.is_finite() or abs(result) > Decimal('1e18') or (result < 0 and not signed):
        raise ValueError('来源数值越界')
    return format(result.normalize(), 'f')


def source_row(kind, row, stock=None):
    expected = {'dividends': DIVIDEND_COLUMNS, 'additional_issues': ISSUE_COLUMNS,
                'rights_issues': RIGHTS_COLUMNS}[kind]
    if set(row) != set(expected):
        raise ValueError('增发送配来源字段不匹配')
    if kind == 'dividends':
        base = security(**stock)
        data = dict(report_date=day(row['fhbgq'], True), announcement_date=day(row['ygrq']),
            record_date=day(row['gqdjr']), ex_date=day(row['cqcxr']),
            bonus_per_share=number(row['T013'], '0.1'), transfer_per_share=number(row['T014'], '0.1'),
            cash_per_share=number(row['T015'], '0.1'), total_bonus_per_share=number(row['szzs'], '0.1'),
            status=row['fajd'], tax_basis='含税', earnings_per_share=number(row['T006'], signed=True),
            net_assets_per_share=number(row['T010'], signed=True),
            capital_reserve_per_share=number(row['T012'], signed=True),
            retained_profit_per_share=number(row['T009'], signed=True))
        if not isinstance(data['status'], str) or not data['status'] or len(data['status']) > 80:
            raise ValueError('分红方案进度无效')
        total = sum(Decimal(data[k] or '0') for k in ('bonus_per_share', 'transfer_per_share'))
        if data['total_bonus_per_share'] is not None and total != Decimal(data['total_bonus_per_share']):
            raise ValueError('送转合计与分项不一致')
        # TDX can return parallel payouts on the same report/announcement dates.
        # Amounts distinguish source plans; never arbitrarily select or add them.
        identity = [base['market'], base['code'], data['report_date'], data['announcement_date'],
                    data['cash_per_share'] or '0', data['bonus_per_share'] or '0',
                    data['transfer_per_share'] or '0']
        event_date = data['ex_date'] or data['report_date']
    else:
        base = security({0: 'SZ', 1: 'SH', 2: 'BJ'}.get(row['sc']), row['code'], row['name'])
        if kind == 'additional_issues':
            if type(row['rec_id']) is not int or row['rec_id'] <= 0 or row['fxfs'] not in ('定向增发', '公开增发'):
                raise ValueError('增发来源编号或发行方式无效')
            data = dict(source_id=str(row['rec_id']), issue_method=row['fxfs'],
                issued_shares=number(row['T005'], 10000, required=True),
                shares_before=number(row['T039'], 10000), shares_after=number(row['T040'], 10000),
                issue_price=number(row['T012']), issue_date=day(row['fxrq']),
                public_issue_date=day(row['T043']), private_issue_date=day(row['T046']),
                listing_date=day(row['T080']), record_date=day(row['T037']),
                subscription_code=row['T048'] or None, lock_months=number(row['T097']),
                announcement_date=None, status='来源发行记录')
            identity = [base['market'], base['code'], data['source_id']]
            event_date = data['issue_date'] or data['listing_date']
        else:
            data = dict(rights_per_share=number(row['T005'], '0.1', required=True),
                rights_price=number(row['T006'], required=True), issued_shares=number(row['T015'], 10000, required=True),
                shares_before=number(row['T022'], 10000), shares_after=number(row['T023'], 10000),
                record_date=day(row['gqdjr'], True), ex_date=day(row['cqjzr'], True),
                payment_start=day(row['jqqsr'], True), payment_end=day(row['jqjzr']),
                listing_date=day(row['T043']), subscription_code=row['T038'] or None,
                announcement_date=None, status='来源配股记录')
            identity = [base['market'], base['code'], data['record_date'],
                        data['subscription_code'], data['payment_start']]
            event_date = data['ex_date']
        if data['subscription_code'] is not None and (not isinstance(data['subscription_code'], str)
                                                     or len(data['subscription_code']) > 20):
            raise ValueError('认购代码无效')
    return {**base, 'record_key': digest(identity), 'event_date': event_date, 'data': data}


def ordered(rows):
    return sorted(rows, key=lambda row: row['record_key'])


def unit_key(row):
    return row['market'] + ':' + row['code']


def validate_rows(kind, unit, rows):
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError('单证券方案数量超出上限')
    seen = set()
    for row in rows:
        if set(row) != {'market', 'code', 'name', 'record_key', 'event_date', 'data'}:
            raise ValueError('规范方案字段无效')
        security(row['market'], row['code'], row['name'])
        if unit_key(row) != unit or not re.fullmatch('[0-9a-f]{64}', row['record_key']):
            raise ValueError('方案证券关联或业务键无效')
        if row['record_key'] in seen:
            raise ValueError('方案业务键重复')
        seen.add(row['record_key'])
        # Reconstruct source fields to exercise the same strict business validation.
        from empire.plugins.datasets.capital_validation import as_source
        raw, stock = as_source(kind, row)
        rebuilt = source_row(kind, raw, stock)
        if kind == 'additional_issues':
            from empire.plugins.datasets.issue_detail import validate
            rebuilt['data']['detail'] = validate(row['data'].get('detail'))
        if rebuilt != row:
            raise ValueError('方案未按正式业务契约规范化')
    if rows != ordered(rows):
        raise ValueError('方案业务键须按序提交')
    return rows
