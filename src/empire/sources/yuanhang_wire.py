"""Bounded Yuanhang native table decoding; no network, authentication or storage."""
import math
import struct
from datetime import datetime
from decimal import Decimal


class EmptyHistoryResponse(ValueError):
    """The source returned no tables, which alone proves neither absence nor identity."""

    def __init__(self, instance: int, request_id: int):
        super().__init__('Yuanhang empty response needs separate security and absence evidence')
        self.instance, self.request_id = instance, request_id


def snappy_block(data: bytes, limit: int, reserve=None) -> bytes:
    """Decode raw Snappy, checking the advertised size before allocating output."""
    if type(limit) is not int or limit < 0:
        raise ValueError('Invalid Snappy input budget')
    size = shift = pos = 0
    while True:
        if pos >= len(data) or shift > 28:
            raise ValueError('Invalid Snappy length')
        value = data[pos]
        pos += 1
        size |= (value & 127) << shift
        if not value & 128:
            break
        shift += 7
    if size > limit:
        raise ValueError('Snappy expansion exceeds limit')
    if reserve is not None:
        reserve(size)
    out = bytearray()
    while pos < len(data) and len(out) < size:
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length >= 60:
                count = length - 59
                if pos + count > len(data):
                    raise ValueError('Truncated Snappy literal length')
                length = int.from_bytes(data[pos:pos + count], 'little')
                pos += count
            length += 1
            if pos + length > len(data) or len(out) + length > size:
                raise ValueError('Snappy literal exceeds bounds')
            out.extend(data[pos:pos + length])
            pos += length
        else:
            count = {1: 1, 2: 2, 3: 4}[kind]
            if pos + count > len(data):
                raise ValueError('Truncated Snappy copy')
            offset = int.from_bytes(data[pos:pos + count], 'little')
            pos += count
            length = (4 + ((tag >> 2) & 7)) if kind == 1 else (1 + (tag >> 2))
            if kind == 1:
                offset |= (tag & 224) << 3
            if not 0 < offset <= len(out) or len(out) + length > size:
                raise ValueError('Snappy copy exceeds bounds')
            while length:
                chunk = min(offset, length)
                start = len(out) - offset
                out.extend(out[start:start + chunk])
                length -= chunk
    if pos != len(data) or len(out) != size:
        raise ValueError('Snappy size or trailing bytes mismatch')
    return bytes(out)


def hxlong(value: int):
    if value in (0x80000000, 0xFFFFFFFF):
        return None
    magnitude = Decimal(value & 0x7FFFFFF)
    exponent = (value >> 28) & 7
    magnitude = magnitude.scaleb(-exponent if value >> 31 else exponent)
    return -magnitude if value & 0x8000000 else magnitude


def scalar(cell, kind):
    if kind == 1:
        return None if cell[:1] == b'\xff' else cell.split(b'\0', 1)[0].decode('gbk')
    # Descriptor width is storage stride; the scalar type still has fixed width.
    # The client reads int32 for kind 4 even when a field reserves eight bytes.
    if kind == 2 and len(cell) >= 4:
        return hxlong(int.from_bytes(cell[:4], 'little'))
    if kind == 3 and len(cell) >= 8:
        value = None if cell[:8] == b'\0' * 7 + b'\x80' else struct.unpack('<d', cell[:8])[0]
        if value is not None and not math.isfinite(value):
            raise ValueError('Nonfinite HX double')
        return value
    if kind == 4 and len(cell) >= 4:
        return None if cell[:4] in (b'\xff' * 4, b'\0' * 3 + b'\x80') else struct.unpack('<i', cell[:4])[0]
    raise ValueError(f'Unsupported HX field encoding kind={kind} width={len(cell)}')


def decode_table(data: bytes, limit: int, reserve=None):
    if type(limit) is not int or not 22 <= len(data) <= limit:
        raise ValueError('Truncated HX table')
    version = data[:6]
    if version in (b'hx1.2\0', b'hx1.3\0'):
        if reserve is not None:
            reserve(6)
        data = version + snappy_block(data[6:], limit - 6, reserve)
    elif version != b'hx1.0\0':
        raise ValueError('Unsupported HX table version')
    elif reserve is not None:
        reserve(len(data))
    if len(data) > limit or len(data) < 22:
        raise ValueError('HX table exceeds bounds')
    rows, header_size, row_size, columns, stamp = struct.unpack_from('<iIHHI', data, 6)
    start = 22 + columns * 8
    if not 0 <= rows <= 100000 or not 1 <= columns <= 256 or start > len(data):
        raise ValueError('Invalid HX table dimensions')
    descriptors = [struct.unpack_from('<IBBH', data, 22 + i * 8) for i in range(columns)]
    if (len({field for field, *_ in descriptors}) != columns
            or any(not width or kind not in (1, 2, 3, 4)
                   or width < {1: 1, 2: 4, 3: 8, 4: 4}[kind]
                   for _, kind, _, width in descriptors)
            or sum(width for _, _, _, width in descriptors) != row_size
            or header_size != start or start + rows * row_size + stamp != len(data)):
        raise ValueError('Invalid HX fields or row extent')
    result = []
    for row in range(rows):
        point, offset = {}, start + row * row_size
        for field, kind, flags, width in descriptors:
            cell = data[offset:offset + width]
            offset += width
            try:
                point[field] = scalar(cell, kind)
            except ValueError as exc:
                raise ValueError(f'{exc}; field={field}, row={row}, date={point.get(1)}, '
                                 f'encoding={kind}, cell={cell[:8].hex()}') from exc
        result.append(point)
    extra, offset = {}, start + rows * row_size
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated HX extension descriptor')
        field, kind, flags, width = struct.unpack_from('<IBBH', data, offset)
        offset += 8
        if field in extra or not width or offset + width > len(data):
            raise ValueError('Invalid HX extension extent or duplicate identity')
        extra[field] = scalar(data[offset:offset + width], kind)
        offset += width
    return dict(version=version.rstrip(b'\0').decode(), row_count=rows, row_size=row_size,
                header_size=header_size, extra_bytes=stamp, fields=descriptors, rows=result,
                extra=extra, decoded_bytes=len(data))


def decode_response(body: bytes, *, instance: int, request_id: int, limit=1048576, reserve=None):
    if type(limit) is not int or not 17 <= len(body) <= limit:
        raise ValueError('V2 response length invalid')
    head_size, actual_instance, actual_id, flags, payload_size, blocks = struct.unpack_from('<HiIHiB', body)
    if ((head_size, actual_instance, actual_id, flags, payload_size, blocks)
            == (17, instance, request_id, 0, 0, 0) and len(body) == 17):
        raise EmptyHistoryResponse(instance, request_id)
    if (head_size != 17 or (actual_instance, actual_id) != (instance, request_id)
            or flags != 1 or payload_size != len(body) - 17 or not 1 <= blocks <= 64):
        raise ValueError('V2 response identity, format or extent mismatch')
    result, offset, remaining = [], 17, limit
    for _ in range(blocks):
        if offset + 4 > len(body):
            raise ValueError('Truncated V2 block')
        size = struct.unpack_from('<I', body, offset)[0]
        offset += 4
        if size < 22 or offset + size > len(body):
            raise ValueError('V2 block extent mismatch')
        table = decode_table(body[offset:offset + size], remaining, reserve)
        remaining -= table['decoded_bytes']
        result.append(table)
        offset += size
    if offset != len(body):
        raise ValueError('Unexpected V2 trailing bytes')
    return result


def validate_history_tables(tables, *, security: str, required_fields: set[int],
                            start: int, end: int, repeatable_fields=frozenset(), identical_fields=frozenset()):
    """Validate separate date grids without positional joins or silent omissions.

    Empty source responses still need a separately verified source contract;
    this function must not turn a rejected/no-data envelope into empty success.
    """
    if not tables or not required_fields or 1 not in required_fields or start > end:
        raise ValueError('Invalid history validation contract')
    present = set()
    for table in tables:
        if not table['rows']:
            raise ValueError('History empty table contract not yet verified')
        if table['extra'].get(5) != security:
            raise ValueError('History source security identity mismatch')
        fields = {field for field, *_ in table['fields']}
        if 1 not in fields or (present & fields) - {1}:
            raise ValueError('History date field missing or duplicate field tables')
        present.update(fields)
        previous, previous_row = None, None
        for row in table['rows']:
            day = row.get(1)
            if type(day) is not int or not start <= day <= end:
                raise ValueError('History date outside requested range')
            try:
                datetime.strptime(str(day), '%Y%m%d')
            except ValueError:
                raise ValueError('Invalid history calendar date') from None
            if set(row) != fields:
                raise ValueError('History row field set mismatch')
            if previous is not None and (day < previous or day == previous
                    and fields != repeatable_fields and not (fields == identical_fields and row == previous_row)):
                raise ValueError('History duplicate or unordered date')
            previous, previous_row = day, row
    if not required_fields <= present:
        raise ValueError('History required fields omitted by source')
