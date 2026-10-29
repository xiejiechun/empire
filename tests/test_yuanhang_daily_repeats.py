"""301110 source repeats: complete-frame evidence, exact collapse and conflict rejection."""
import struct
from datetime import date

import pytest

from empire.sources.yuanhang_coverage import audit_year, year_proof
from empire.sources.yuanhang_history import normalize_daily
from empire.sources.yuanhang_payload import daily_years, validate_year
from empire.sources.yuanhang_wire import decode_response
from tests.test_yuanhang_history import tables
from tests.test_yuanhang_payload import CODE, snapshot


def raw_bar(day=20221010):
    return {1: day, 7: 34.95, 8: 34.95, 9: 33.22, 11: 33.53, 13: 562150., 19: 19057729.}


def decoded_daily(rows, *, declared=None):
    fields = list(rows[0])
    descriptors = b''.join(struct.pack('<IBBH', f, 4 if f == 1 else 3, 0, 4 if f == 1 else 8) for f in fields)
    data = b''.join(struct.pack('<i', row[1]) + b''.join(
        b'\0' * 7 + b'\x80' if row[f] is None else struct.pack('<d', row[f]) for f in fields[1:]) for row in rows)
    security = ('USHT' + CODE[:6]).encode() + b'\0'
    extra = struct.pack('<IBBH', 5, 1, 0, len(security)) + security
    table = b'hx1.0\0' + struct.pack('<iIHHI', len(rows) if declared is None else declared,
        22 + len(descriptors), 4 + 8 * (len(fields)-1), len(fields), len(extra)) + descriptors + data + extra
    body = struct.pack('<I', len(table)) + table
    return decode_response(struct.pack('<HiIHiB', 17, 1, 210, 1, len(body), 1) + body, instance=1, request_id=210)


def normalized_daily(rows):
    return normalize_daily(decoded_daily(rows), unified_code=CODE, native_market='USHT',
                           start=date(1900,1,1), end=date(2026,10,23))


def test_declared_complete_daily_frame_allows_only_exact_adjacent_full_row_repeats():
    rows = [raw_bar(), raw_bar(), raw_bar(), raw_bar(20221011)]
    decoded = decoded_daily(rows)
    assert decoded[0]['row_count'] == len(decoded[0]['rows']) == 4
    result = normalized_daily(rows)
    assert [b.trade_date.isoformat() for b in result] == ['2022-10-10','2022-10-11']
    assert result == normalized_daily([raw_bar(), raw_bar(20221011)])
    unit, = daily_years(snapshot(result), code=CODE, through=date(2022,12,31))
    assert unit['history_count'] == unit['source_count'] == 2
    with pytest.raises(ValueError):
        decoded_daily(rows, declared=3)


@pytest.mark.parametrize('field', [7,8,9,11,13,19])
def test_conflicting_same_date_cannot_be_collapsed(field):
    changed = raw_bar()
    changed[field] += 1
    with pytest.raises(ValueError, match='duplicate'):
        normalized_daily([raw_bar(), changed])


def test_explicit_null_repeat_is_equal_but_null_and_zero_conflict():
    row = {**raw_bar(), 13: None, 19: None}
    result, = normalized_daily([row, dict(row)])
    assert result.volume_shares is result.amount_yuan is None
    with pytest.raises(ValueError, match='duplicate'):
        normalized_daily([row, {**row, 13: 0.}])


def test_repeat_cannot_hide_descending_dates_or_ambiguous_partial_grids():
    with pytest.raises(ValueError, match='unordered'):
        normalized_daily([raw_bar(), raw_bar(20221011), raw_bar()])
    parts = tables([{1: 20221010, 7: 34.95}, {1: 20221010, 7: 34.95}], 'USHT' + CODE[:6])
    parts += tables([{k:v for k,v in raw_bar().items() if k != 7}], 'USHT' + CODE[:6])
    with pytest.raises(ValueError, match='duplicate'):
        normalize_daily(parts, unified_code=CODE, native_market='USHT', start=date(1900,1,1), end=date(2026,10,23))


def test_equal_raw_counts_and_unique_counts_do_not_replace_date_and_content_proofs():
    def unit(last):
        return daily_years(snapshot(normalized_daily([raw_bar(), raw_bar(), raw_bar(last)])),
                           code=CODE, through=date(2022,12,31))[0]
    expected, wrong = unit(20221011), unit(20221012)
    assert expected['source_count'] == wrong['source_count'] == 2
    assert expected['key_hash'] != wrong['key_hash']
    assert audit_year(expected, wrong['rows'], year_proof(wrong))
    with pytest.raises(ValueError, match='契约'):
        validate_year({**expected, 'contract': 4})
