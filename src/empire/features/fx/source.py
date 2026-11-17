"""Strict public wh JSONP identities, annual membership and source day boundaries."""
import json
import re
from datetime import datetime, timedelta

from empire.core.time import CHINA
from empire.features.fx.contract import day, number, symbol, validate_rows


class QuoteUnavailable(ValueError):
    """A valid quote head explicitly contains no current prices."""


class DailyQuoteUnavailable(ValueError):
    """A dated native daily response explicitly contains four empty prices."""


def decode(body, callback):
    if not isinstance(body, str) or len(body) > 2 * 1024 * 1024:
        raise ValueError('汇率响应正文超限')
    match = re.fullmatch(r'\s*' + re.escape(callback) + r'\((\{.*\})\)\s*;?\s*', body, re.S)
    if not match:
        raise ValueError('汇率JSONP身份不符或响应截断')
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('汇率JSON字段重复')
            result[k] = v
        return result
    value = json.loads(match[1], object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('汇率响应不是对象')
    return value


def candle(body, code, unit):
    symbol(code)
    value = decode(body, f'quotebridge_v4_line_wh_{code}_01_{unit}')
    raw = value.get('data')
    if not isinstance(raw, str) or not raw:
        raise ValueError('汇率来源未提供有效日线，不视为空历史')
    rows = []
    for record in raw.rstrip(';').split(';'):
        cells = record.split(',')
        if len(cells) != 11 or not re.fullmatch(r'\d{8}', cells[0]):
            raise ValueError('汇率日线来源字段结构改变')
        stamp = cells[0]
        rows.append([day(f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}'), *map(number, cells[1:5])])
    validate_rows(rows, None if unit == 'last' else unit)
    return value, rows


def closed_through(now):
    if now.tzinfo is None:
        raise ValueError('汇率核验时间必须带时区')
    local = now.astimezone(CHINA)
    # Public wh supplies source calendar labels, not an authoritative final bit.
    # At/after 09:00 accept only earlier labels; early manual runs defer one more
    # label to avoid treating an overnight candle as closed during DST transitions.
    return (local.date() - timedelta(days=1 if local.hour >= 9 else 2)).isoformat()


def current_candle(body, code, observed):
    """The chart's dated daily row is separate from its historical response."""
    symbol(code)
    value = decode(body, f'quotebridge_v6_line_wh_{code}_01_today')
    if set(value) != {'wh_' + code} or not isinstance(value['wh_' + code], dict):
        raise ValueError('汇率当日日线品种身份不符')
    item = value['wh_' + code]
    stamp = item.get('1')
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{8}', stamp):
        raise ValueError('汇率当日日线来源日期无效')
    stamp = day(f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}')
    if stamp > observed.astimezone(CHINA).date().isoformat():
        raise ValueError('汇率当日日线来源日期异常超前')
    if type(item.get('open')) is not int or item['open'] not in (0, 1):
        raise ValueError('汇率当日日线交易状态无效')
    if all(item.get(key) == '' for key in ('7', '8', '9', '11')):
        raise DailyQuoteUnavailable(f'{code}：来源当日日线暂无报价（{stamp}），保留原数据和断点')
    return [stamp, *[number(item.get(key)) for key in ('7', '8', '9', '11')]]


def recent(body, code, now):
    value, rows = candle(body, code, 'last')
    counts = value.get('year')
    if not isinstance(counts, dict) or not 1 <= len(counts) <= 150:
        raise ValueError('汇率历史年份目录缺失')
    counts = dict(counts)
    for year, count in counts.items():
        if (not re.fullmatch(r'\d{4}', year) or not 1900 <= int(year) <= now.astimezone(CHINA).year
                or type(count) is not int or not 1 <= count <= 366):
            raise ValueError('汇率历史年份/数量无效')
    first = value.get('start')
    if not isinstance(first, str) or not re.fullmatch(r'\d{8}', first):
        raise ValueError('汇率来源历史起点缺失')
    first = day(f'{first[:4]}-{first[4:6]}-{first[6:]}')
    if (type(value.get('num')) is not int or value['num'] != len(rows)
            or str(value.get('total', '')) != str(sum(counts.values()))
            or first[:4] != min(counts) or rows[0][0] < first
            or rows[-1][0][:4] != max(counts) or rows[-1][0] > now.astimezone(CHINA).date().isoformat()):
        raise ValueError('汇率来源目录、总数或日期边界不一致')
    for year in {r[0][:4] for r in rows}:
        if sum(r[0][:4] == year for r in rows) > counts.get(year, 0):
            raise ValueError('汇率近期日期集合与年份数量冲突')
    source_tail, source_years = rows[-2:], dict(counts)
    cutoff = closed_through(now)
    for row in rows:
        if row[0] > cutoff:
            counts[row[0][:4]] -= 1
    rows = [r for r in rows if r[0] <= cutoff]
    counts = {y: n for y, n in counts.items() if n}
    if not rows:
        raise ValueError('汇率来源尚无已结束日线')
    return dict(start=first, end=rows[-1][0], years=counts, rows=rows,
                source_tail=source_tail, source_years=source_years)


def annual(body, code, year, snapshot):
    _, rows = candle(body, code, year)
    rows = [r for r in rows if r[0] <= snapshot['end']]
    expected = [r for r in snapshot['rows'] if r[0][:4] == str(year)]
    count = snapshot['years'][str(year)]
    # Annual caches can lag a recent suffix, but must have an overlapping anchor.
    if rows and expected and rows[-1][0] >= expected[0][0]:
        suffix = [r for r in expected if r[0] > rows[-1][0]]
        if len(rows) + len(suffix) == count:
            rows.extend(suffix)
    if len(rows) != count or not rows or year == int(snapshot['start'][:4]) and rows[0][0] != snapshot['start']:
        raise ValueError('汇率年度数量或来源起点不完整，保留断点')
    by_date = {r[0]: r for r in rows}
    for row in expected:
        if row[0] not in by_date:
            raise ValueError('汇率年度与近期日期集合不一致')
        # The recent response owns corrections on already present overlapping keys.
        by_date[row[0]] = row
    return validate_rows([by_date[d] for d in sorted(by_date)], year)


def realtime(body, code, observed):
    symbol(code)
    value = decode(body, f'quotebridge_v4_realhead_wh_{code}_last').get('items')
    if (not isinstance(value, dict) or len(value) > 160 or value.get('5') != code
            or value.get('marketid') != '97'):
        raise ValueError('汇率实时品种或市场身份不符')
    times = {}
    for key, pattern in (('time', '%Y-%m-%d %H:%M:%S 北京时间'), ('updateTime', '%Y-%m-%d %H:%M')):
        raw = value.get(key)
        if not isinstance(raw, str):
            raise ValueError('汇率实时来源时间缺失')
        stamp = datetime.strptime(raw, pattern).replace(tzinfo=CHINA)
        if stamp > observed.astimezone(CHINA) + timedelta(minutes=5):
            raise ValueError('汇率来源时间异常超前')
        times[key] = stamp.isoformat()
    if all(value.get(field) == '' for field in ('10', '7', '8', '9')) and '6' in value:
        if value['6'] != '':
            number(value['6'])
        raise QuoteUnavailable(f'{code}：来源暂无报价，保留上次有效值和采样时间')
    quote = {k: number(value.get(f)) for k, f in
             (('latest', '10'), ('open', '7'), ('high', '8'), ('low', '9'), ('previous_close', '6'))}
    return dict(symbol=code, unified_code=code + '.FX', **quote,
        source_time=times['time'], source_update_time=times['updateTime'], observed_at=observed.isoformat())
