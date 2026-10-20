"""The industry endpoint returns a whole month and has no page-size parameter."""
from datetime import date

from empire.features.unlock_industries.contract import NUMBERS, canonical_number, validate
from empire.features.unlocks.contract import shares, source_day, text_value
from empire.sources.tdx_unlock import results

DIRECTORY_URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_cgbd_cache'
URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_cgbd_dxfhy'
SOURCE_COLUMNS = ['T001', 'T003', 'T004', 'MarketCap', 'NegotiableCap', 'zszbl', 'ltszbl']


def parse_directory(value):
    dates, metadata = results(value, [['T008'], ['mxt']])
    if not 1 <= len(dates) <= 120 or len(metadata) != 1:
        raise ValueError('解禁行业目录为空或超限')
    months = []
    for row in dates:
        raw = row[0]
        if not isinstance(raw, str) or len(raw) != 6 or not raw.isdigit():
            raise ValueError('解禁行业目录月份错误')
        months.append(date(int(raw[:4]), int(raw[4:]), 1).isoformat())
    if len(set(months)) != len(months):
        raise ValueError('解禁行业目录重复')
    from empire.features.unlock_industries.contract import basis
    return sorted(months), basis(source_day(metadata[0][0]))


def parse_month(value, month, basis_date):
    raw, echo = results(value, [SOURCE_COLUMNS, ['sstart']])
    if echo != [[month[:7].replace('-', '')]]:
        raise ValueError('解禁行业响应月份不匹配')
    rows = []
    for record in raw:
        row = dict(unlock_month=month, basis_date=basis_date, industry=text_value(record[0], 200, True))
        for key, value in zip(NUMBERS, record[1:], strict=True):
            number = shares(value, source=key in ('shares', 'unlock_value'))
            row[key] = canonical_number(number)
        rows.append(row)
    rows.sort(key=lambda r: r['industry'])
    validate(month, basis_date, rows)
    return rows


__all__ = ['DIRECTORY_URL', 'URL', 'parse_directory', 'parse_month']
