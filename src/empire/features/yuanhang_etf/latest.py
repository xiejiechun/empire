"""A bounded atomic current ETF result, never an archive or history store."""
import base64
import binascii
import json
import re
import zlib
from datetime import UTC, datetime
from decimal import Decimal

from empire.contracts.plugin import PluginManifest
from empire.features.yuanhang_etf.contract import (
    ETF_LIMIT,
    LATEST_BYTES,
    LATEST_FIELDS,
    digest,
    identity,
)

TTL = 7 * 86400
_NUMBER = r'(?:(?:0|-?[1-9][0-9]{0,17})(?:\.[0-9]{0,9}[1-9])?|-0\.[0-9]{0,9}[1-9])'
CANONICAL_VALUES = re.compile(rf'(?:={_NUMBER}|null)(?:,(?:={_NUMBER}|null)){{7}}\Z', re.ASCII)
ROW_KEYS = {'code', 'native_market', 'name', 'quote_at', 'net_value_date', *LATEST_FIELDS.values()}
SAVE = """
local old = redis.call('HGET', KEYS[1], 'version')
if old and tonumber(old) >= tonumber(ARGV[1]) then return 0 end
redis.call('HSET', KEYS[1], 'version', ARGV[1], 'body', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
READ = """
if redis.call('HSTRLEN', KEYS[1], 'body') > tonumber(ARGV[1]) then
  return redis.error_reply('ETF latest body exceeds limit')
end
return redis.call('HMGET', KEYS[1], 'version', 'body')
"""


def validate(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {'schema', 'catalog_hash', 'observed_at', 'rows'} or snapshot['schema'] != 1:
        raise ValueError('ETF最新结果结构无效')
    stamp = datetime.fromisoformat(snapshot['observed_at'])
    if stamp.tzinfo is None or (stamp - datetime.now(UTC)).total_seconds() > 300:
        raise ValueError('ETF采样时刻无效')
    rows = snapshot['rows']
    if not isinstance(rows, list) or not 1 <= len(rows) <= ETF_LIMIT:
        raise ValueError('ETF最新结果数量无效')
    previous = ''
    catalog = []
    for row in rows:
        if not isinstance(row, dict) or row.keys() != ROW_KEYS:
            raise ValueError('ETF最新结果字段无效')
        identity(row['code'], row['native_market'])
        if row['code'] <= previous or not isinstance(row['name'], str) or not row['name'].strip() or len(row['name']) > 100:
            raise ValueError('ETF最新身份顺序或名称无效')
        if row['quote_at'] is not None or row['net_value_date'] is not None:
            raise ValueError('ETF尚未声明来源报价及净值日期格式')
        try:
            values = ','.join('null' if (v := row[k]) is None else '='+v for k in LATEST_FIELDS.values())
        except TypeError:
            raise ValueError('ETF最新数值未规范化') from None
        if not CANONICAL_VALUES.fullmatch(values):
            raise ValueError('ETF最新数值未规范化')
        # Exact fixed keys, <=100 Unicode name characters and eight <=30-byte
        # canonical decimals bound each encoded row below 4KiB, without encoding
        # every row a second time on each page read.
        catalog.append({k: row[k] for k in ('code', 'native_market', 'name')})
        previous = row['code']
    if digest(catalog) != snapshot['catalog_hash']:
        raise ValueError('ETF最新目录集合证明不符')
    return stamp


class LatestQuery:
    manifest = PluginManifest('data.yuanhang_etf_latest', '远航ETF最新行情查询', requires=('redis.store',),
        provides=('yuanhang.etf.latest.query',))

    async def start(self, context):
        store = context.get('redis.store')
        self.redis, self.key = store.client, f'{store.prefix}:yuanhang:etf:latest'
        return {'yuanhang.etf.latest.query': self}

    async def save(self, snapshot):
        stamp = validate(snapshot)
        body = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(body.encode()) > LATEST_BYTES:
            raise ValueError('ETF最新整份正文超过24MiB')
        body = 'z1:' + base64.b64encode(zlib.compress(body.encode(), 1)).decode('ascii')
        if len(body) > LATEST_BYTES:
            raise ValueError('ETF最新编码正文超过24MiB')
        return bool(await self.redis.eval(SAVE, 1, self.key, int(stamp.timestamp()*1000000), body, TTL))

    async def browse(self, code='', search='', after=None, limit=200, order=None):
        if not isinstance(code, str) or len(code) > 9 or not isinstance(search, str) or len(search) > 100 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('ETF最新查询范围无效')
        field, direction = 'unified_code', 'asc'
        numeric = {*LATEST_FIELDS.values(), 'change', 'change_percent', 'amplitude'}
        if order is not None:
            if not isinstance(order, dict) or set(order) != {'field', 'direction'} or order['field'] not in {
                    'unified_code', 'name', *numeric, 'observed_at', 'quote_at', 'net_value_date', 'availability', 'sampling_stale'} or order['direction'] not in ('asc', 'desc'):
                raise ValueError('ETF最新排序无效')
            field, direction = order['field'], order['direction']
        version, body = await self.redis.eval(READ, 1, self.key, LATEST_BYTES)
        if not body:
            return dict(rows=[], total=0, next=None, message='暂无Redis最新结果，请先采样；Redis重启后需重新采样。')
        snapshot = decode_body(body)
        stamp = validate(snapshot)
        version = version.decode() if isinstance(version, bytes) else version
        if str(int(stamp.timestamp()*1000000)) != version:
            raise ValueError('ETF最新结果版本损坏')
        signature = digest([code, search, field, direction])
        offset = 0
        if after is not None:
            if (not isinstance(after, dict) or set(after) != {'version', 'query', 'offset'} or after['query'] != signature
                    or type(after['offset']) is not int or not 0 <= after['offset'] <= ETF_LIMIT):
                raise ValueError('ETF最新分页游标无效')
            if after['version'] != version:
                raise ValueError('ETF最新结果已更新，请刷新后重新翻页')
            offset = after['offset']
        rows = []
        stale = (datetime.now(UTC)-stamp).total_seconds() > 180
        for raw in snapshot['rows']:
            if code.upper() not in raw['code'] or search.casefold() not in (raw['code']+' '+raw['name']).casefold():
                continue
            value = (raw['code'] if field == 'unified_code' else stamp.isoformat() if field == 'observed_at'
                else stale if field == 'sampling_stale' else availability(raw) if field == 'availability'
                else derived(raw, field) if field in ('change', 'change_percent', 'amplitude') else raw[field])
            rows.append((Decimal(value) if value is not None and field in numeric else value, raw))
        valid = [pair for pair in rows if pair[0] is not None]
        valid.sort(key=lambda pair: (pair[0], pair[1]['code']), reverse=direction == 'desc')
        rows = valid + sorted((pair for pair in rows if pair[0] is None), key=lambda pair: pair[1]['code'])
        next_page = dict(version=version, query=signature, offset=offset+limit) if offset+limit < len(rows) else None
        displayed = [dict(raw, unified_code=raw['code'], observed_at=stamp.isoformat(), source_time_unknown=True,
            sampling_stale=stale, availability=availability(raw),
            **{key: derived(raw, key) for key in ('change', 'change_percent', 'amplitude')}) for _, raw in rows[offset:offset+limit]]
        return dict(rows=displayed, total=len(rows), next=next_page,
            message='仅Redis最新值；涨跌/涨幅/振幅由来源基础值计算。采样时间不代表来源报价时间，净值日期未知。')

    async def stop(self):
        self.redis = None

    def health(self):
        return {'status': 'ok' if getattr(self, 'redis', None) else 'stopped'}


def availability(row):
    return '来源暂无现价' if row['latest'] is None else '来源有值，报价时间未知'


def decode_body(body):
    if not isinstance(body, str) or not body.startswith('z1:') or len(body) > LATEST_BYTES:
        raise ValueError('ETF最新正文编码或大小无效')
    try:
        compressed = base64.b64decode(body[3:], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, LATEST_BYTES+1)
        if len(raw) > LATEST_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('ETF最新正文解压超限、截断或尾部异常')
        return json.loads(raw)
    except (binascii.Error, zlib.error, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('ETF最新正文损坏') from exc


def derived(row, field):
    previous = row['previous_close']
    if previous is None:
        return None
    previous = Decimal(previous)
    if field == 'amplitude':
        return (format((Decimal(row['high'])-Decimal(row['low']))/previous*100, 'f')
            if previous and row['high'] is not None and row['low'] is not None else None)
    if row['latest'] is None:
        return None
    change = Decimal(row['latest'])-previous
    return format(change, 'f') if field == 'change' else format(change/previous*100, 'f') if previous else None
