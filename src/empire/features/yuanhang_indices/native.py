"""Request-specific bounded native index decoding; no stock identity coercion."""
import configparser
import re
import struct
import zlib
from datetime import date

from empire.contracts.security import index_code
from empire.features.yuanhang_indices.contract import INDEX_LIMIT, MARKETS, identity, number
from empire.sources.yuanhang_history import DAILY_FIELDS, _same_grid, day_number
from empire.sources.yuanhang_transport import request
from empire.sources.yuanhang_wire import decode_response, decode_table, validate_history_tables


def expand_codes(value):
    result = []
    for token in value.split(','):
        if not token:
            continue
        ends = token.split('-')
        first = index_code(ends[0])
        if len(ends) == 1:
            result.append(first)
        elif len(ends) == 2:
            last = index_code(ends[1])
            match = re.fullmatch(r'([0-9A-Z]*?)([0-9]+)', first)
            prefix, start = match.groups()
            if not last.startswith(prefix) or not last[len(prefix):].isdigit():
                raise ValueError('指数代码区间前缀不一致')
            stop = int(last[len(prefix):])
            if not int(start) <= stop < int(start) + INDEX_LIMIT:
                raise ValueError('指数代码展开超限')
            result.extend(prefix + str(v).zfill(len(start)) for v in range(int(start), stop + 1))
        else:
            raise ValueError('指数代码区间格式无效')
        if len(result) > INDEX_LIMIT:
            raise ValueError('指数目录超过上限')
    return result


def market_codes(body, market, *, instance, limit, reserve=None):
    if len(body) < 21 or len(body) > limit:
        raise ValueError('指数市场文件长度无效')
    header = struct.unpack_from('<HiIHiB', body)
    if header != (17, instance, 240, 0x0202, len(body) - 17, 1):
        raise ValueError('指数市场文件身份或帧长度无效')
    size = struct.unpack_from('<I', body, 17)[0]
    if not 4 < size <= limit:
        raise ValueError('指数市场文件展开超限')
    if reserve:
        reserve(size)
    decoder = zlib.decompressobj()
    plain = decoder.decompress(body[21:], size + 1)
    if len(plain) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('指数市场文件压缩长度无效')
    text = plain[4:].rstrip(b'\0').decode('gbk')
    ini = configparser.ConfigParser(interpolation=None, strict=True)
    ini.read_string(text)
    section = ini[MARKETS[market]]
    codes = []
    for key, value in section.items():
        if re.fullmatch(r'codelist(?:_[0-9]+)?', key):
            codes.extend(expand_codes(value))
    if not codes or len(codes) != len(set(codes)) or len(codes) != int(section['totalstock']):
        raise ValueError('指数市场文件目录集合或数量不符')
    if market == 'USTI':
        codes = [c for c in codes if c == '899050']
        if not codes:
            raise ValueError('远航D2目录缺少北证50身份')
    return sorted(codes)


def names(body, market, codes, *, instance, limit, reserve=None):
    if len(body) < 21 or len(body) > limit:
        raise ValueError('指数名称响应长度无效')
    if struct.unpack_from('<HiIHiB', body) != (17, instance, 200, 1, len(body) - 17, 1):
        raise ValueError('指数名称响应身份无效')
    size = struct.unpack_from('<I', body, 17)[0]
    if size != len(body) - 21:
        raise ValueError('指数名称块长度无效')
    table = decode_table(body[21:], limit, reserve, text_encodings={55: 'utf8'})
    if {f for f, *_ in table['fields']} != {5, 55}:
        raise ValueError('指数名称字段不符')
    result = []
    for row in table['rows']:
        native, name = row[5], row[55]
        if not isinstance(native, str) or not native.startswith(market) or not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('指数名称或市场身份无效')
        result.append(dict(code=index_code(native[4:]), name=name.strip(), native_market=market))
    actual = [r['code'] for r in result]
    if len(actual) != len(set(actual)) or set(actual) != set(codes):
        raise ValueError('指数名称批量响应缺码、额外代码或重复')
    return sorted(result, key=lambda r: r['code'])


def daily(tables, code, market, start, end):
    validate_history_tables(tables, security=identity(code, market), required_fields=set(DAILY_FIELDS),
        start=day_number(start), end=day_number(end), identical_fields=DAILY_FIELDS)
    result = []
    for row in _same_grid(tables, DAILY_FIELDS):
        stamp = str(row[1])
        result.append([date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:])).isoformat()]
            + [number(row[f]) for f in (7, 8, 9, 11, 13, 19)])
    return result


async def fetch_catalog(http, session, *, project_id):
    result = []
    for i, market in enumerate(MARKETS):
        instance = i * 2 + 1
        query = f'id=240&market={market}&timemaa=0&zipversion=2&instance={instance}'.encode('ascii')
        codes = await request(http, session, query,
            lambda b, n, r: market_codes(b, market, instance=instance, limit=n, reserve=r), project_id=project_id)
        instance += 1
        query = (f'id=200&market={market}&codelist={",".join(codes)}&datatype=5,55'
                 f'&zipversion=2&instance={instance}').encode('ascii')
        result.extend(await request(http, session, query,
            lambda b, n, r: names(b, market, codes, instance=instance, limit=n, reserve=r), project_id=project_id))
    if not 1 <= len(result) <= INDEX_LIMIT or len(result) != len({r['code'] for r in result}):
        raise ValueError('远航指数完整目录集合无效')
    return sorted(result, key=lambda r: r['code'])


async def fetch_daily(http, session, code, market, start, end, *, project_id, reservation=None):
    identity(code, market)
    query = (f'id=210&market={market}&code={code}&start={day_number(start)}&end={day_number(end)}'
             '&period=16384&datatype=1,7,8,9,11,13,19&zipversion=2&instance=1').encode('ascii')
    return await request(http, session, query,
        lambda b, n, r: daily(decode_response(b, instance=1, request_id=210, limit=n, reserve=r), code, market, start, end),
        project_id=project_id, reservation=reservation)
