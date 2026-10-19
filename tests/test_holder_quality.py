"""Source quality is independent of response/identity integrity for every kind."""
import copy
from datetime import date

import pytest

from empire.features.holders.contract import KINDS, quality_details, quality_flags, validate
from empire.features.holders.source import parse
from tests.test_ths_holders import STOCK, source


def quality_source(kind, shape):
    body = source()
    ident = KINDS[kind][1]
    start = body.index('<div id="' + ident + '">')
    end = body.find('<div id="', start + 1)
    end = end if end >= 0 else len(body)
    block = body[start:end]
    bond = kind == 'bond_holders'
    if shape == 'missing_ratio':
        block = block.replace('<td>1.00' + ('' if bond else '%') + '</td>', '<td>--</td>')
    elif shape == 'missing_quantity':
        block = block.replace('<td>' + ('10.00' if bond else '10.00万') + '</td>', '<td>--</td>')
    elif shape == 'missing_exit_quantity':
        block = block.replace('退出人</td><td>' + ('5' if bond else '5.00万') + '</td>', '退出人</td><td>—</td>')
    elif shape == 'future_date':
        block = block.replace('2026-06-30', '2099-06-30')
    elif shape == 'quantity_mismatch':
        block = block.replace('100.00万', '200.00万')
    elif shape == 'ratio_mismatch':
        block = block.replace('<em>10.00%</em>', '<em>20.00%</em>')
    elif shape == 'missing_quantity_summary':
        block = block.replace('<em>100.00万' + ('张' if bond else '股') + '</em>', '--')
    elif shape == 'missing_ratio_summary':
        block = block.replace('<em>10.00%</em>', '--')
    else:
        raise ValueError(shape)
    return body[:start] + block + body[end:]


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('shape,flag', [('missing_ratio', 1), ('quantity_mismatch', 2), ('ratio_mismatch', 4),
                                      ('missing_quantity_summary', 8), ('missing_ratio_summary', 16), ('missing_quantity', 32), ('missing_exit_quantity', 64), ('future_date', 128)])
def test_all_kinds_keep_source_values_with_exact_quality_flags(kind, shape, flag):
    row = parse(quality_source(kind, shape), kind, STOCK)[0]
    assert row['quality_flags'] == flag and len(row['members']) == 11
    assert [issue['flag'] for issue in quality_details(row)] == [flag]
    assert validate(kind, STOCK['unified_code'], [row])
    if flag == 1:
        assert all(m['ratio'] is None for m in row['members'][:10])
    elif flag == 2:
        assert row['total_quantity'] == '2000000' and row['members'][0]['quantity'] == '100000'
    elif flag == 4:
        assert row['total_ratio'] == '20' and row['members'][0]['ratio'] == '1'
    elif flag == 8:
        assert row['total_quantity'] is row['total_quantity_scale'] is row['total_quantity_decimals'] is None
    elif flag == 16:
        assert row['total_ratio'] is None
    elif flag in (32, 64):
        group = 'current' if flag == 32 else 'exited'
        assert all(m['quantity'] is m['quantity_scale'] is m['quantity_decimals'] is None for m in row['members'] if m['member_group'] == group)
    else:
        assert row['report_date'] == '2099-06-30'
    bad = copy.deepcopy(row)
    bad['quality_flags'] = 0
    with pytest.raises(ValueError, match='质量标记'):
        validate(kind, STOCK['unified_code'], [bad], today=date(2026, 10, 17))
    # A quality marker cannot authorize duplicate/missing identities.
    bad = copy.deepcopy(row)
    bad['members'][1]['holder_name'] = bad['members'][0]['holder_name']
    with pytest.raises(ValueError, match='不同集合'):
        validate(kind, STOCK['unified_code'], [bad])


def test_partial_ratios_do_not_claim_equality_and_source_zero_is_distinct():
    row = parse(source(), 'top_holders', STOCK)[0]
    row['members'][0]['ratio'] = None
    row['total_ratio'] = '0'
    row['quality_flags'] = quality_flags(row)
    assert row['quality_flags'] == 5
    validate('top_holders', STOCK['unified_code'], [row])
    row['members'][0]['ratio'] = '0'
    row['quality_flags'] = quality_flags(row)
    assert row['quality_flags'] == 4
    assert len(quality_details(row)) == 1


@pytest.mark.parametrize('dash', ['-', '--', '—', ''])
def test_unknown_quantity_keeps_nulls_but_bad_units_and_half_nulls_fail(dash):
    body = source().replace('<td>10.00万</td>', '<td>' + dash + '</td>')
    row = parse(body, 'top_holders', STOCK)[0]
    assert row['quality_flags'] == 32
    assert all(m['quantity'] is None for m in row['members'][:10])
    # A partial known sum cannot prove equality, but can prove overflow.
    row['members'][0].update(quantity='2000000', quantity_scale=1, quantity_decimals=0)
    row['quality_flags'] = quality_flags(row)
    assert row['quality_flags'] == 34
    validate('top_holders', STOCK['unified_code'], [row])
    row['members'][1]['quantity_scale'] = 1
    with pytest.raises(ValueError, match='不得伪造精度'):
        validate('top_holders', STOCK['unified_code'], [row])
    with pytest.raises(ValueError, match='单位'):
        parse(source().replace('<td>10.00万</td>', '<td>10.00万张</td>'), 'top_holders', STOCK)
    zero = parse(source().replace('<td>10.00万</td>', '<td>0</td>'), 'top_holders', STOCK)[0]
    assert zero['members'][0]['quantity'] == '0' and zero['quality_flags'] == 2


def test_future_flag_is_observation_bound_and_rechecked_at_ingest():
    from datetime import UTC, datetime

    from empire.contracts.data import make_envelope
    from empire.features.holders.dataset import HolderDataset
    body = source().replace('2026-06-30', '2026-10-20')
    before = {k: parse(body, k, STOCK, today=date(2026, 10, 17)) for k in KINDS}
    assert all(rows[0]['quality_flags'] == 128 for rows in before.values())
    for kind, rows in before.items():
        validate(kind, STOCK['unified_code'], rows)  # Stored observation is stable.
    mapping = HolderDataset()
    e = make_envelope(source='ths', dataset='holders.reports', schema_version=5,
        job_key=mapping.JOB, business_key=STOCK['unified_code'], run_id='test', batch_id='test',
        payload=dict(page=1, unit=STOCK['unified_code'], reports=before, manifest=None, gaps=[])).model_copy(
            update={'observed_at': datetime(2026, 10, 17, tzinfo=UTC)})
    assert mapping.normalize(e)
    with pytest.raises(ValueError, match='质量标记'):
        mapping.normalize(e.model_copy(update={'observed_at': datetime(2026, 10, 21, tzinfo=UTC)}))
    after = {k: parse(body, k, STOCK, today=date(2026, 10, 21)) for k in KINDS}
    assert all(rows[0]['quality_flags'] == 0 for rows in after.values())
    damaged = copy.deepcopy(before)
    damaged['top_holders'][0]['quality_flags'] = 0
    with pytest.raises(ValueError, match='质量标记'):
        mapping.normalize(e.model_copy(update={'raw_payload': {**e.raw_payload, 'reports': damaged}}))


@pytest.mark.parametrize('damage', ['bond_name', 'unit', 'structure'])
def test_quality_does_not_admit_required_field_or_structure_failure(damage):
    body = quality_source('bond_holders', 'missing_ratio')
    if damage == 'bond_name':
        body = body.replace('<span>燃23转债</span>', '<span></span>')
    elif damage == 'unit':
        body = body.replace('持有数量(万张)', '持有数量(股)')
    else:
        body = body.replace('id="bondholder_1"', 'id="wrong"')
    with pytest.raises(ValueError) as error:
        parse(body, 'bond_holders', STOCK, today=date(2026, 10, 14))
    assert error.value.holder_metadata['kind'] == 'bond_holders'
    if damage == 'bond_name':
        assert error.value.holder_metadata['report_date']
