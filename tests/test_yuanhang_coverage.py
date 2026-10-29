from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal

from empire.sources.yuanhang_client import HistorySnapshot
from empire.sources.yuanhang_coverage import (
    audit_financial,
    audit_year,
    financial_proofs,
    year_proof,
)
from empire.sources.yuanhang_history import DailyBar
from empire.sources.yuanhang_payload import daily_years


def payloads():
    bars = tuple(DailyBar('000001.SZ', date.fromisoformat(day),
                         *map(Decimal, ('2', '3', '1', '2', '100')), None)
                 for day in ('1991-04-03', '1991-04-04', '1991-04-05', '1993-01-04'))
    return daily_years(HistorySnapshot('USZA', datetime(2026, 10, 24, tzinfo=UTC), bars),
                       code='000001.SZ', through=date(1993, 12, 31))


def test_formal_annual_rows_and_proof_match_source_including_empty_year():
    for p in payloads():
        assert audit_year(p, deepcopy(p['rows']), year_proof(p)) == []
    empty = year_proof(payloads()[1])
    assert empty['row_count'] == 0
    assert empty['first_date'] is empty['last_date'] is None


def test_same_count_and_extrema_cannot_hide_wrong_middle_date():
    p = payloads()[0]
    rows = deepcopy(p['rows'])
    rows[1][0] = '1991-04-03'
    assert audit_year(p, rows, year_proof(p)) == ['invalid_stored_rows', 'content_mismatch']


def test_same_keys_and_proof_cannot_hide_changed_business_value():
    p = payloads()[0]
    rows = deepcopy(p['rows'])
    rows[1][-1] = '0'
    assert audit_year(p, rows, year_proof(p)) == ['content_mismatch']


def test_old_contract_or_missing_proof_does_not_pass():
    p = payloads()[0]
    proof = year_proof(p)
    assert audit_year(p, p['rows'], None) == ['missing_proof']
    proof['contract_version'] = 0
    assert audit_year(p, p['rows'], proof) == ['proof_mismatch']


def test_missing_entire_year_is_not_covered_by_later_year_success():
    first, _, last = payloads()
    assert audit_year(last, last['rows'], year_proof(last)) == []
    assert audit_year(first, [], None) == ['missing_proof', 'invalid_stored_rows', 'content_mismatch']


def test_completed_year_proof_does_not_change_as_cutoff_advances():
    p = payloads()[0]
    later = {**p, 'through': '2026-10-23'}
    assert year_proof(p) == year_proof(later)
    assert year_proof(p)['verified_through'] == '1991-12-31'


def test_unchanged_current_year_accepts_earlier_content_change_cutoff():
    p = payloads()[-1]
    earlier = {**p, 'through': '1993-01-04'}
    assert audit_year(p, p['rows'], year_proof(earlier)) == []
    corrupt = {**year_proof(earlier), 'content_hash': '0' * 64}
    assert audit_year(p, p['rows'], corrupt) == ['proof_mismatch']


def financial():
    from empire.sources.yuanhang_payload import CONTRACT
    return dict(contract=CONTRACT, code='000001.SZ', native_market='USZA', actions=[],
                capital=[[kind, '1990-01-01', '100'] for kind in ('circulating', 'free_float', 'total')])


def test_financial_proofs_bind_empty_actions_to_same_positive_capital_response():
    p = financial()
    proofs = financial_proofs(p)
    assert proofs['actions']['response_group'] == proofs['capital']['response_group']
    assert proofs['actions']['first_date'] is None
    assert audit_financial(p, p['actions'], p['capital'], proofs) == []


def test_financial_same_count_changed_kind_or_content_fails():
    p = financial()
    rows = deepcopy(p['capital'])
    rows[1][2] = '101'
    assert audit_financial(p, [], rows, financial_proofs(p)) == ['capital_content_mismatch']
    rows[1][0] = 'circulating'
    assert 'invalid_stored_rows' in audit_financial(p, [], rows, financial_proofs(p))


def test_financial_heads_from_different_response_cannot_be_combined():
    p = financial()
    proofs = financial_proofs(p)
    revised = deepcopy(p)
    revised['capital'][0][2] = '90'
    proofs['capital'] = financial_proofs(revised)['capital']
    assert audit_financial(p, [], p['capital'], proofs) == ['capital_proof_mismatch']
