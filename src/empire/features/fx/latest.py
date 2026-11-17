"""One bounded Hash: twelve latest values, no history, SQL or archive envelopes."""
import json
from datetime import UTC, datetime

from empire.features.fx.contract import SYMBOLS, number, symbol

TTL = 7 * 86400
SAVE = """
local old = redis.call('HGET', KEYS[1], 'version:' .. ARGV[1])
if old and tonumber(old) >= tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3], 'version:' .. ARGV[1], ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""


class LatestStore:
    def __init__(self, redis):
        self.redis = redis
        self.key = f'{redis.prefix}:fx:latest'

    async def save(self, quote):
        code, stamp = validate(quote)
        body = json.dumps(quote, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(body.encode()) > 2048:
            raise ValueError('汇率最新值超出单品种2KiB上限')
        return bool(await self.redis.client.eval(SAVE, 1, self.key, code,
            str(int(stamp.timestamp() * 1000000)), body, TTL))

    async def browse(self, code='', after=None, limit=50, order=None):
        if code and (len(code) > 6 or not code.isascii() or not code.isalpha()):
            raise ValueError('汇率品种筛选无效')
        if after is not None or not 1 <= limit <= 200:
            raise ValueError('最新行情仅一页，不能读取历史快照')
        codes = [s for s in SYMBOLS if s.startswith(code.upper())]
        bodies = await self.redis.client.hmget(self.key, codes) if codes else []
        rows, now = [], datetime.now(UTC)
        for s, body in zip(codes, bodies):
            if not body:
                continue
            if len(body) > 2048:
                raise ValueError('汇率最新值正文损坏')
            value = json.loads(body)
            stored, stamp = validate(value)
            if stored != s:
                raise ValueError('汇率最新值身份损坏')
            value.update(name=SYMBOLS[s][0], unit=SYMBOLS[s][2],
                sampling_stale=(now - stamp).total_seconds() > 180)
            rows.append(value)
        if order is not None:
            allowed = {*rows[0]} if rows else {'unified_code', 'symbol', 'name', 'unit', 'latest', 'open', 'high', 'low', 'previous_close', 'observed_at', 'source_time', 'source_update_time', 'sampling_stale'}
            if not isinstance(order, dict) or set(order) != {'field', 'direction'} or order['field'] not in allowed or order['direction'] not in ('asc', 'desc'):
                raise ValueError('汇率最新行情排序无效')
            from decimal import Decimal
            field = order['field']
            rows.sort(key=lambda row: (Decimal(row[field]) if field in ('latest', 'open', 'high', 'low', 'previous_close') else row[field], row['symbol']), reverse=order['direction'] == 'desc')
        return dict(rows=rows, total=len(rows), next=None,
                    message='仅保存最新值；采样过期不代表市场休市，来源时间单独展示。')


def validate(quote):
    required = {'symbol', 'unified_code', 'latest', 'open', 'high', 'low', 'previous_close', 'source_time', 'source_update_time', 'observed_at'}
    if not isinstance(quote, dict) or set(quote) != required:
        raise ValueError('汇率最新值字段损坏')
    code = symbol(quote['symbol'])
    if quote['unified_code'] != code + '.FX':
        raise ValueError('汇率最新值身份损坏')
    for key in ('latest', 'open', 'high', 'low', 'previous_close'):
        if number(quote[key]) != quote[key]:
            raise ValueError('汇率最新值价格未规范化')
    stamps = [datetime.fromisoformat(quote[k]) for k in ('observed_at', 'source_time', 'source_update_time')]
    now = datetime.now(UTC)
    if any(s.tzinfo is None for s in stamps) or any((s - now).total_seconds() > 300 for s in stamps):
        raise ValueError('汇率最新值时间无效或超前')
    return code, stamps[0]
