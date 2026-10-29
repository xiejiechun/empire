from copy import deepcopy

import pytest

from scripts.migrate_yuanhang_ranges import upgrade


def fixture():
    return ({'contract_version': 5, 'units': {'000001.SZ': dict(
        versions={'2025': '2026-10-23T08:00:00.000000+00:00'},
        verified_through='2026-10-23', native_market='USZA')}},
        [dict(unified_code='000001.SZ', quote_year=2025, contract_version=5,
              source_count=200, row_count=200, verified_through='2025-12-31')])


def test_explicit_migration_preserves_prior_input_and_is_idempotent():
    previous, heads = fixture()
    before = deepcopy(previous)
    upgraded = upgrade(previous, heads)
    assert previous == before
    unit = upgraded['units']['000001.SZ']
    assert unit['price_ranges']['2025'] == [['2025-01-01', '2025-12-31',
                                           '2026-10-23T08:00:00.000000+00:00']]
    assert upgrade(upgraded, heads) == upgraded


@pytest.mark.parametrize('case', ['missing_head', 'missing_state', 'bad_contract', 'bad_counts', 'naive_version'])
def test_missing_or_inconsistent_proof_is_not_promoted(case):
    previous, heads = fixture()
    if case == 'missing_head':
        heads = []
    elif case == 'missing_state':
        previous['units'] = {}
    elif case == 'bad_contract':
        heads[0]['contract_version'] = 4
    elif case == 'bad_counts':
        heads[0]['row_count'] = 199
    else:
        previous['units']['000001.SZ']['versions']['2025'] = '2026-10-23T08:00:00'
    with pytest.raises(ValueError):
        upgrade(previous, heads)
