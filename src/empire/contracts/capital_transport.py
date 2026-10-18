"""Lossless bounded wire matrices; SQL and business fingerprints stay typed."""
import base64
import binascii
import json
import zlib

from empire.contracts.ths_capital import TABLES, fields

SCHEMA = 2
MAX_RAW = 8 * 1024**2
MAX_BODY = 512 * 1024


def pack(rows):
    if not isinstance(rows, dict) or set(rows) != set(TABLES):
        raise ValueError('资本运作传输表集合无效')
    if any(not isinstance(rows[t], list) for t in TABLES) or sum(map(len, rows.values())) > 10000:
        raise ValueError('资本运作传输行数无效')
    if any(not isinstance(r, dict) or set(r) != set(fields(t)) for t in TABLES for r in rows[t]):
        raise ValueError('资本运作传输字段集合无效')
    matrix = {t: [[r[k] for k in fields(t)] for r in rows[t]] for t in TABLES}
    raw = json.dumps(matrix, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_RAW:
        raise ValueError('资本运作规范矩阵超过8MiB')
    body = base64.b64encode(zlib.compress(raw)).decode('ascii')
    if len(body) > MAX_BODY:
        raise ValueError('资本运作压缩正文超过512KiB')
    return dict(codec='zlib-json-v1', bytes=len(raw), body=body)


def unpack(value):
    if (not isinstance(value, dict) or set(value) != {'codec', 'bytes', 'body'}
            or value['codec'] != 'zlib-json-v1' or type(value['bytes']) is not int
            or not 0 <= value['bytes'] <= MAX_RAW or not isinstance(value['body'], str)
            or len(value['body']) > MAX_BODY):
        raise ValueError('资本运作压缩传输契约无效')
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(base64.b64decode(value['body'], validate=True), value['bytes'] + 1)
        if len(raw) != value['bytes'] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('资本运作解压长度或压缩流无效')
        matrix = json.loads(raw)
    except (binascii.Error, zlib.error, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('资本运作传输解码失败') from exc
    if not isinstance(matrix, dict) or set(matrix) != set(TABLES):
        raise ValueError('资本运作传输表集合无效')
    if any(not isinstance(matrix[t], list) for t in TABLES) or sum(map(len, matrix.values())) > 10000:
        raise ValueError('资本运作传输行数无效')
    rows = {}
    for table in TABLES:
        columns = fields(table)
        if any(not isinstance(r, list) or len(r) != len(columns) for r in matrix[table]):
            raise ValueError('资本运作传输矩阵缺列')
        rows[table] = [dict(zip(columns, r, strict=True)) for r in matrix[table]]
    return rows
