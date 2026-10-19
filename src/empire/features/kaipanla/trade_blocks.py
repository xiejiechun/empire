"""Bounded typed binary trade blocks, not a compressed raw JSON response."""
import hashlib
import struct
import zlib
from datetime import timedelta

from empire.features.kaipanla.storage_contract import numeric_values

BLOCK_POINTS = 200
POINT_BYTES = 62  # uint32 seconds + uint16 type mask + seven int64/IEEE754 binary64 unions
FORMATS = {mask: struct.Struct('>IH'+''.join('d' if mask & (1 << i) else 'q' for i in range(7)))
           for mask in range(128)}
MAX_BYTES = BLOCK_POINTS * POINT_BYTES


def pack(points, params):
    blocks = []
    for start in range(0, len(points), BLOCK_POINTS):
        chunk = points[start:start+BLOCK_POINTS]
        body = bytearray()
        for point in chunk:
            h, m, s = map(int, point[0].split(':'))
            _, mask = numeric_values(point[1:])
            body.extend(FORMATS[mask & 127].pack(h*3600+m*60+s, mask, *point[1:]))
        compressed = zlib.compress(body, 6)
        blocks.append(dict(**params, block_seq=start//BLOCK_POINTS, first_seq=start,
            last_seq=start+len(chunk)-1, first_time=chunk[0][0], last_time=chunk[-1][0],
            point_count=len(chunk), format_version=1, body=compressed, block_hash=hashlib.sha256(compressed).hexdigest()))
    return blocks


def unpack(block):
    if hashlib.sha256(block['body']).hexdigest() != block['block_hash']:
        raise ValueError('分笔块内容摘要不匹配')
    expected = block['point_count']*POINT_BYTES
    if not 1 <= block['point_count'] <= BLOCK_POINTS or block['format_version'] != 1:
        raise ValueError('分笔块契约无效')
    decoder = zlib.decompressobj()
    body = decoder.decompress(block['body'], MAX_BYTES+1)
    if len(body) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('分笔块损坏、超限或截断')
    points = []
    for start in range(0, expected, POINT_BYTES):
        sec, mask = struct.unpack_from('>IH', body, start)
        if not 0 <= sec < 86400 or mask >= 16384:
            raise ValueError('分笔时间或数值类型标记无效')
        _, _, *values = FORMATS[mask & 127].unpack_from(body, start)
        h, rest = divmod(sec, 3600)
        m, s = divmod(rest, 60)
        points.append([f'{h:02}:{m:02}:{s:02}', *values])
    if block['last_seq']-block['first_seq']+1 != len(points) or block['first_seq'] != block['block_seq']*BLOCK_POINTS:
        raise ValueError('分笔块序号不连续')
    for key, point in (('first_time', points[0]), ('last_time', points[-1])):
        value = block[key]
        if isinstance(value, timedelta):
            sec = int(value.total_seconds())
            h, rest = divmod(sec, 3600)
            m, s = divmod(rest, 60)
            value = f'{h:02}:{m:02}:{s:02}'
        if value != point[0]:
            raise ValueError('分笔块时间边界不匹配')
    return points
