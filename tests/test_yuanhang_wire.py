import struct

import pytest

from empire.sources.yuanhang_wire import (
    EmptyHistoryResponse,
    decode_response,
    hxlong,
    scalar,
    snappy_block,
    validate_history_tables,
)


def packet(*, date=20261023, rows=1, tail=b''):
    descriptor = struct.pack('<IBBH', 1, 4, 0, 4)
    table = b'hx1.0\0' + struct.pack('<iIHHI', rows, 30, 4, 1, 0) + descriptor
    table += struct.pack('<i', date) + tail
    body = struct.pack('<I', len(table)) + table
    return struct.pack('<HiIHiB', 17, 7, 210, 1, len(body), 1) + body


def test_snappy_literal_and_overlapping_copy():
    assert snappy_block(b'\x05\x10hello', 5) == b'hello'
    assert snappy_block(b'\x06\x00a\x12\x01\x00', 6) == b'aaaaaa'


@pytest.mark.parametrize('data,limit', [
    (b'\x80' * 6, 10), (b'\x7f', 10), (b'\x05\x10hell', 5),
    (b'\x06\x00a\x12\x00\x00', 6), (b'\x01\x00aEXTRA', 10),
])
def test_snappy_corruption_or_oversize_rejected(data, limit):
    with pytest.raises(ValueError):
        snappy_block(data, limit)


def test_decimal_prices_are_not_binary_float_and_null_is_not_zero():
    assert str(hxlong(0xC000A21C)) == '4.1500'
    assert hxlong(0) == 0
    assert hxlong(0x80000000) is None
    assert hxlong(0xFFFFFFFF) is None
    assert scalar(struct.pack('<i', 20261023) + b'\x00' * 4, 4) == 20261023


def test_response_identity_and_declared_set_extent():
    decoded = decode_response(packet(), instance=7, request_id=210)
    assert decoded[0]['rows'] == [{1: 20261023}]
    with pytest.raises(ValueError, match='identity'):
        decode_response(packet(), instance=8, request_id=210)
    for data in (packet(rows=2), packet(tail=b'\x00'), packet()[:-1]):
        with pytest.raises(ValueError):
            decode_response(data, instance=7, request_id=210)


def test_outer_aggregate_byte_limit():
    with pytest.raises(ValueError, match='length'):
        decode_response(packet(), instance=7, request_id=210, limit=20)


def test_source_empty_is_distinct_from_valid_empty_history_and_checks_request_identity():
    response = struct.pack('<HiIHiB', 17, 7, 211, 0, 0, 0)
    with pytest.raises(EmptyHistoryResponse) as caught:
        decode_response(response, instance=7, request_id=211)
    assert (caught.value.instance, caught.value.request_id) == (7, 211)
    with pytest.raises(ValueError, match='identity'):
        decode_response(response, instance=8, request_id=211)
    with pytest.raises(ValueError, match='identity'):
        decode_response(response + b'\0', instance=7, request_id=211)


@pytest.mark.parametrize('kind,width', [(1, 0), (2, 1), (3, 4), (4, 2), (9, 4)])
def test_invalid_descriptor_rejected_even_without_rows(kind, width):
    descriptor = struct.pack('<IBBH', 1, kind, 0, width)
    table = b'hx1.0\0' + struct.pack('<iIHHI', 0, 30, width, 1, 0) + descriptor
    body = struct.pack('<I', len(table)) + table
    response = struct.pack('<HiIHiB', 17, 7, 210, 1, len(body), 1) + body
    with pytest.raises(ValueError, match='fields'):
        decode_response(response, instance=7, request_id=210)


def history_table(field, dates, security='USZA300176'):
    return dict(extra={5: security}, fields=[(1, 4, 0, 4), (field, 3, 0, 8)],
                rows=[{1: day, field: 100} for day in dates])


def validate(tables):
    validate_history_tables(tables, security='USZA300176', required_fields={1, 402, 407},
                            start=20200101, end=20261023)


def test_capital_tables_keep_distinct_source_date_grids():
    validate([history_table(402, [20200102]), history_table(407, [20200103, 20200106])])


@pytest.mark.parametrize('tables,reason', [
    ([history_table(402, [])], 'empty table'),
    ([history_table(402, [20200102])], 'omitted'),
    ([history_table(402, [20200102], 'USHA600519')], 'identity'),
    ([history_table(402, [20200102, 20200102])], 'duplicate'),
    ([history_table(402, [20200103, 20200102])], 'unordered'),
    ([history_table(402, [20200230])], 'calendar'),
    ([history_table(402, [20261024])], 'outside'),
    ([history_table(402, [20200102]), history_table(402, [20200103])], 'duplicate field'),
])
def test_invalid_source_sets_cannot_become_complete_history(tables, reason):
    with pytest.raises(ValueError, match=reason):
        validate(tables)

def test_nonfinite_double_still_rejected_with_field_and_date():
    from empire.sources.yuanhang_wire import decode_table
    descriptors = struct.pack('<IBBH', 1, 4, 0, 4) + struct.pack('<IBBH', 407, 3, 0, 8)
    body = b'hx1.0\0' + struct.pack('<iIHHI', 1, 38, 12, 2, 0) + descriptors
    body += struct.pack('<id', 20261028, float('nan'))
    with pytest.raises(ValueError, match=r'Nonfinite HX double; field=407, row=0, date=20261028'):
        decode_table(body, 1024)
