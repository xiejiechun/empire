from copy import deepcopy
from datetime import datetime

import pytest

from scripts.migrate_yuanhang_ranges import restore_missing, upgrade


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


def test_missing_state_restore_uses_individual_cutoffs_and_beijing_versions():
    _, heads = fixture()
    head = dict(heads[0], native_market='USZA', version_observed_at=datetime(2026, 10, 23, 16),
                key_hash='a' * 64, content_hash='b' * 64)
    newer = dict(head, quote_year=2026, verified_through='2026-10-22')
    restored = restore_missing([head, newer])['units']['000001.SZ']
    assert restored['price_ranges']['2025'][0][:2] == ['2025-01-01', '2025-12-31']
    assert restored['price_ranges']['2026'] == [['2026-01-01', '2026-10-22',
                                               '2026-10-23T08:00:00.000000+00:00']]
    for field, value in [('contract_version', 4), ('row_count', 199), ('verified_through', '2026-12-31'),
                         ('key_hash', ''), ('version_observed_at', datetime(2025, 1, 1))]:
        with pytest.raises(ValueError):
            restore_missing([dict(head, **{field: value})])
    with pytest.raises(ValueError):
        restore_missing([head, head])
