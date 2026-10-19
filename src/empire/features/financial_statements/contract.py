"""Independent statement identities and strict, precision-aware source matrices."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal

KINDS = {
    'income': ('利润表', 'benefit', 'income_statement'),
    'balance': ('资产负债表', 'debt', 'balance_statement'),
    'cashflow': ('现金流量表', 'cash', 'cashflow_statement'),
}
REQUIRED = {
    'income': ('*营业总收入', '*净利润', '*归属于母公司所有者的净利润'),
    'balance': ('*资产合计', '*负债合计', '*所有者权益（或股东权益）合计'),
    'cashflow': ('*经营活动产生的现金流量净额', '*投资活动产生的现金流量净额',
                 '*筹资活动产生的现金流量净额', '*现金及现金等价物净增加额', '*期末现金及现金等价物余额'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def validate_report_date(day):
    # Source matrices also contain non-quarter reporting cutoffs (920000: 2014-07-31).
    if not isinstance(day, str):
        raise ValueError('财报报告期无效')
    try:
        parsed = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError('财报报告期无效') from exc
    if parsed.isoformat() != day or not date(1000, 1, 1) <= parsed <= date.today():
        raise ValueError('财报报告期无效')


def amount(value):
    if value is False or value in ('--', ''):
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('财报数值必须为来源金额字符串')
    match = re.fullmatch(r'(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(万亿|亿|万)?', value)
    if not match:
        raise ValueError('财报金额格式或单位无效')
    numeric = match[1].replace(',', '')
    scale = {'万亿': 10**12, '亿': 10**8, '万': 10**4, None: 1}[match[2]]
    precision = len(numeric.split('.')[1]) if '.' in numeric else 0
    return {'value': format((Decimal(numeric) * scale).normalize(), 'f'),
            'resolution': format(Decimal(scale).scaleb(-precision).normalize(), 'f')}


def parse(kind, body, stock):
    if kind not in KINDS or not isinstance(body, dict) or not isinstance(body.get('flashData'), str):
        raise ValueError('财报响应结构无效')
    matrix = json.loads(body['flashData'])
    titles, report = matrix.get('title'), matrix.get('report')
    if not isinstance(titles, list) or not isinstance(report, list) or not 2 <= len(titles) <= 400:
        raise ValueError('财报科目矩阵缺失')
    if len(titles) != len(report) or not isinstance(report[0], list) or not 1 <= len(report[0]) <= 300:
        raise ValueError('财报矩阵不完整或空表')
    dates = report[0]
    for day in dates:
        validate_report_date(day)
    if dates != sorted(set(dates), reverse=True):
        raise ValueError('财报报告期重复或乱序')
    fields = {}
    for title, values in zip(titles[1:], report[1:], strict=True):
        if (not isinstance(title, list) or len(title) != 5 or not isinstance(title[0], str)
                or not title[0] or len(title[0]) > 200 or type(title[4]) is not bool
                or not isinstance(values, list) or len(values) != len(dates)):
            raise ValueError('财报科目或数据列缺失')
        if not title[4]:
            if any(v != '' for v in values):
                raise ValueError('财报分组标题含有金额')
            continue
        if title[1] != '元' or title[0] in fields:
            raise ValueError('财报科目重复或单位未知')
        fields[title[0]] = [amount(v) for v in values]
    if not set(REQUIRED[kind]) <= set(fields):
        raise ValueError('财报核心科目缺失')
    rows = []
    for index, day in enumerate(dates):
        values = {key: row[index] for key, row in fields.items()}
        rows.append({**stock, 'report_date': day, 'basis': 'source_report',
                     'currency': 'CNY', 'period_basis': 'instant' if kind == 'balance' else 'year_to_date',
                     'announcement_date': None, 'fields': values})
    return validate_rows(kind, stock['market'] + ':' + stock['code'], rows)


def validate_rows(kind, unit, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 300:
        raise ValueError('财报单元为空或超限')
    dates = []
    for row in rows:
        if set(row) != {'market', 'code', 'name', 'report_date', 'basis', 'currency',
                        'period_basis', 'announcement_date', 'fields'}:
            raise ValueError('规范财报字段不匹配')
        if (row['market'] + ':' + row['code'] != unit or not re.fullmatch(r'(SH|SZ|BJ):\d{6}', unit)
                or not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 100
                or row['basis'] != 'source_report' or row['currency'] != 'CNY'
                or row['period_basis'] != ('instant' if kind == 'balance' else 'year_to_date')
                or row['announcement_date'] is not None):
            raise ValueError('财报身份或口径无效')
        day = row['report_date']
        validate_report_date(day)
        dates.append(day)
        fields = row['fields']
        if not isinstance(fields, dict) or not set(REQUIRED[kind]) <= fields.keys() or len(fields) > 400:
            raise ValueError('财报核心字段缺失')
        for key, value in fields.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 200:
                raise ValueError('财报科目无效')
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) != {'value', 'resolution'}:
                raise ValueError('财报金额精度缺失')
            for name in value:
                if not isinstance(value[name], str) or not re.fullmatch(r'-?\d+(?:\.\d+)?', value[name]):
                    raise ValueError('规范金额无效')
            if Decimal(value['resolution']) <= 0 or abs(Decimal(value['value'])) > Decimal('1e20'):
                raise ValueError('财报金额越界')
    if dates != sorted(set(dates), reverse=True):
        raise ValueError('规范报告期重复或乱序')
    return rows


def chain(previous, unit, rows):
    return digest([previous, unit, digest(rows), len(rows)])
