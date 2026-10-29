from copy import deepcopy
from datetime import UTC, datetime

import pytest

from empire.contracts.data import make_envelope
from empire.features.yuanhang import dataset
from empire.features.yuanhang.contract import (
    FINANCIAL_DATASET,
    FINANCIAL_JOB,
    PRICE_DATASET,
    PRICE_JOB,
    SOURCE,
)
from tests.test_yuanhang_payload import annual, financial


def envelope(history=None, *, financial_unit=False, observed=None, page=1):
    history = history if history is not None else financial() if financial_unit else annual()[0]
    e = make_envelope(source=SOURCE, dataset=FINANCIAL_DATASET if financial_unit else PRICE_DATASET,
        business_key=history['code'] + (':financial' if financial_unit else ':' + str(history['year'])),
        job_key=FINANCIAL_JOB if financial_unit else PRICE_JOB, run_id='test', batch_id='test',
        payload=dict(page=page, history=history))
    return e.model_copy(update=dict(observed_at=observed or datetime(2026, 10, 24, tzinfo=UTC)))


def test_year_fingerprint_excludes_other_year_changes_cutoff_and_page():
    e = envelope()
    h = deepcopy(e.raw_payload['history'])
    h.update(history_count=3, through='2024-01-01', history_last='2024-01-01')
    other = envelope(h, page=2)
    left = dataset.fingerprint_plan(e, dataset.normalize(e))[1]
    right = dataset.fingerprint_plan(other, dataset.normalize(other))[1]
    assert left == right


def test_content_value_or_key_changes_change_fingerprint():
    e = envelope()
    h = deepcopy(e.raw_payload['history'])
    h['rows'][0][-1] = '0'
    changed = envelope(h)
    assert dataset.fingerprint_plan(e, dataset.normalize(e)) != dataset.fingerprint_plan(changed, dataset.normalize(changed))


def test_single_security_state_keeps_bounded_year_versions_and_does_not_regress_on_stale():
    e = envelope()
    d = dataset.normalize(e)
    unit = dict(price_ranges={'2020': [['2020-01-01', '2020-12-31', e.observed_at.isoformat(timespec='microseconds')]]})
    outcome = dict(confirmed=[d['history']['code'] + ':2020-10-19'], price_unit=unit)
    state = dataset.archive_state(e, d, outcome, {})
    assert set(state['units']) == {d['history']['code']}
    assert set(state['units'][d['history']['code']]['price_ranges']) == {'2020'}
    assert dataset.archive_state(e, d, dict(confirmed=[]), state) == state


@pytest.mark.parametrize('financial_unit', [False, True])
def test_canonical_normalization_round_trip_and_identity(financial_unit):
    e = envelope(financial_unit=financial_unit)
    d = dataset.normalize(e)
    assert dataset.canonical_payload(e, d) == e.raw_payload
    assert dataset.state_unit(d) == d['history']['code']
    with pytest.raises(ValueError, match='身份'):
        dataset.normalize(e.model_copy(update=dict(business_key='wrong')))
