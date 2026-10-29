"""Bounded transient envelope compression; SQL remains entirely typed columns."""
import base64
import binascii
import json
import zlib

from empire.features.yuanhang_limits.contract import MAX_UNIT_BYTES

MAX_PACKED_BYTES = 480 * 1024


def encode(unit):
    raw = json.dumps(unit, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_UNIT_BYTES:
        raise ValueError('涨停分析规范完整单元超过8MiB')
    packed = base64.b64encode(zlib.compress(raw, level=6)).decode('ascii')
    if len(packed) > MAX_PACKED_BYTES:
        raise ValueError('涨停分析压缩消息超过480KiB；拒绝半池入库')
    return packed


def decode(packed):
    if not isinstance(packed, str) or len(packed) > MAX_PACKED_BYTES:
        raise ValueError('涨停分析压缩消息类型或长度无效')
    try:
        encoded = base64.b64decode(packed, validate=True)
        reader = zlib.decompressobj()
        raw = reader.decompress(encoded, MAX_UNIT_BYTES + 1)
        if len(raw) > MAX_UNIT_BYTES or reader.unconsumed_tail or reader.unused_data or not reader.eof:
            raise ValueError('涨停分析压缩消息截断、尾随内容或解压超限')
        return json.loads(raw)
    except (ValueError, zlib.error, binascii.Error) as exc:
        raise ValueError('涨停分析压缩消息损坏或超限') from exc
