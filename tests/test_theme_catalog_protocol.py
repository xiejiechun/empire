"""Source schema counterexamples; synthetic bodies are not live source evidence."""
import struct
from decimal import Decimal

import pytest

from empire.features.themes.catalog_mapping import history_rows
from empire.features.themes.catalog_protocol import CatalogError, decode_catalog


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number, value):
    if isinstance(value, int):
        return varint(number * 8) + varint(value)
    if isinstance(value, float):
        return varint(number * 8 + 5) + struct.pack('<f', value)
    if isinstance(value, str):
        value = value.encode()
    return varint(number * 8 + 2) + varint(len(value)) + value


def theme(identity='148', *, extra=b''):
    return field(1, identity) + field(2, '军工') + extra


def body(*themes):
    return b''.join(field(10, item) for item in themes)


def test_source_order_new_rows_and_heat_flag_are_distinct():
    decoded = decode_catalog(body(theme('1', extra=field(9, 1)),
                                  theme('2', extra=field(5, 1) + field(6, 1250)),
                                  theme('3', extra=field(9, 1)), theme('4')))
    assert [v.rank_no for v in decoded.themes] == [None, 1, None, 2]
    assert [v.display_order for v in decoded.themes] == [0, 1, 2, 3]
    assert decoded.themes[1].hot_flag == 1
    assert decoded.themes[1].hot_score == 1250


def test_child_identity_is_parent_scoped_and_missing_metrics_stay_missing():
    child = field(1, '7') + field(2, '雷达') + field(4, -1.25) + field(5, 2)
    decoded = decode_catalog(body(theme('1', extra=field(13, child)),
                                  theme('2', extra=field(13, child))))
    a, b = (v.concepts[0] for v in decoded.themes)
    assert a.identity == ('1', '7') and b.identity == ('2', '7')
    assert a.hot_score is None and a.rank_no is None
    assert a.ratio == Decimal('-1.25') and a.limit_up_count == 2


def test_binary32_is_preserved_exactly_without_decimal_guess():
    decoded = decode_catalog(body(theme(extra=field(12, 0.1))))
    assert decoded.themes[0].ratio == Decimal('0.100000001490116119384765625')
    assert decode_catalog(body(theme())).themes[0].ratio == 0


def test_mapping_keeps_child_scope_null_metrics_and_binary32_precision():
    child = field(1, '7') + field(2, '雷达') + field(4, 0.1)
    catalog = decode_catalog(body(theme('1', extra=field(13, child) + field(9, 1)),
                                  theme('2', extra=field(13, child))))
    rows = history_rows(catalog)
    assert [r['theme_id'] for r in rows] == ['1', '1_7', '2', '2_7']
    assert rows[0]['rank_no'] is None and rows[2]['rank_no'] == 1
    assert rows[1]['hot_score'] is None and rows[1]['rank_no'] is None
    assert rows[1]['change_rate'] == '0.100000001490116119384765625'
    assert rows[1]['source_theme_id'] == '1' and rows[1]['concept_id'] == '7'


@pytest.mark.parametrize('payload', [
    b'', b'\x52\x80', b'\x52\x05a', b'\x08' + b'\xff' * 10,
    body(theme(), theme()), body(field(1, '148')),
    body(field(1, '148') + field(2, b'\xff')), body(theme(extra=field(2, '重复'))),
    body(theme(extra=field(14, 1))), body(theme(extra=field(6, 'wrong-wire'))),
    body(theme(extra=field(6, 1 << 32))), body(theme(extra=field(12, float('nan')))),
    body(theme(extra=field(12, float('inf')))), body(theme(extra=b'\x65\x00')),
    body(field(1, '148') + field(2, '***')),
    body(theme(extra=field(13, field(1, '1') + field(2, '子')) * 2)),
])
def test_invalid_catalog_is_rejected_not_salvaged(payload):
    with pytest.raises(CatalogError):
        decode_catalog(payload)


def test_capacity_limits_apply_to_whole_response():
    sample = body(theme(), theme('2'))
    for limits in ({'max_bytes': len(sample) - 1}, {'max_themes': 1}):
        with pytest.raises(CatalogError):
            decode_catalog(sample, **limits)
    children = field(13, field(1, '1') + field(2, '子1'))
    children += field(13, field(1, '2') + field(2, '子2'))
    with pytest.raises(CatalogError):
        decode_catalog(body(theme(extra=children)), max_concepts=1)


def test_parser_cannot_prove_missing_whole_items_without_transport_evidence():
    # Removing an entire valid item is still valid protobuf. Count alone cannot
    # prove source completeness; production must establish message boundaries.
    complete = decode_catalog(body(theme(), theme('2')))
    partial = decode_catalog(body(theme()))
    assert len(complete.themes) == 2 and len(partial.themes) == 1
