"""Finite source proofs reject equal counts with different keys/content and keep routing ownership."""
import asyncio
import importlib
from copy import deepcopy
from pathlib import Path

import pytest

from empire.features.suspensions.contract import normalize_source_row
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('foundation_verification')


@pytest.mark.parametrize('change', ['key', 'name', 'duplicate'])
def test_stock_equal_count_cannot_hide_source_or_content_difference(verifier, change):
    rows = [dict(unified_code='000001.SZ', code='000001', market='SZ', name='平安银行', source_symbol='sz000001'),
            dict(unified_code='600000.SH', code='600000', market='SH', name='浦发银行', source_symbol='sh600000')]
    actual = deepcopy(rows)
    if change == 'duplicate':
        actual[1] = actual[0]
    elif change == 'key':
        actual[0]['unified_code'] = '000002.SZ'
    else:
        actual[0]['name'] = 'changed'
    with pytest.raises(ValueError, match='业务键重复|集合或内容不同'):
        verifier.same_stocks(rows, actual)
    verifier.same_stocks(rows, list(reversed(rows)))


@pytest.mark.parametrize('months', [[], ['2026-10', '2026-10'], ['2026-10', '1990-12'], ['1990-11'], ['2026-13']])
def test_calendar_scope_never_silently_deduplicates_or_changes_boundaries(verifier, months):
    with pytest.raises(ValueError):
        verifier.calendar_plan(months)


@pytest.mark.parametrize('start,end', [('2026-10-20', '2026-10-19'), ('2026-01-01', '2026-10-20'),
                                     ('2004-12-26', '2004-12-27'), ('2026-10-19', '2026-10-20')])
def test_suspension_scope_rejects_out_of_protocol_ranges(verifier, start, end):
    with pytest.raises(ValueError):
        verifier.suspension_plan(start, end)


def test_conflict_observation_preserves_exact_changed_field_and_source_dates(verifier):
    row = normalize_source_row(dict(sc=1, code='603517', name='前名称', tprq='2026-10-19 09:30',
        fprq='2026-10-20 09:30', sj='停牌1天', sjcontent='事项'))
    other = dict(row, name='后名称')
    differences = verifier.suspension_differences({'2026-10-20': [other], '2026-10-19': [row]})
    assert differences[0]['fields'] == {'name': ['前名称', '后名称']}
    assert differences[0]['previous_day'] == '2026-10-19'
    assert differences[0]['day'] == '2026-10-20'
    assert row['name'] == '前名称' and other['name'] == '后名称'


def test_formal_datetime_precision_is_equivalent_but_changed_business_content_is_not(verifier):
    source = dict(market='SH', code='603517', name='绝味食品', suspended_at='2026-10-19T09:30+08:00',
                  resumed_at=None, suspension_type='full_day', source_note='停牌1天', reason='事项')
    actual = dict(source, suspended_at='2026-10-19T09:30:00')
    verifier.same_suspensions([source], [actual])
    for key, value in [('suspended_at', '2026-10-19T09:31:00'), ('name', 'changed'),
                       ('reason', 'other'), ('resumed_at', '2026-10-20T09:30:00')]:
        with pytest.raises(ValueError, match='集合或内容不同'):
            verifier.same_suspensions([source], [dict(actual, **{key:value})])


@pytest.mark.parametrize('failure', [RuntimeError('download failed'), asyncio.CancelledError()])
@pytest.mark.asyncio
async def test_routing_restores_caller_context_on_error_or_cancellation(verifier, failure):
    previous = USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get()
    counts = {}
    async def operation():
        assert USE_PROXY.get() is True and PROXY_FALLBACK.get() is False
        assert ROUTE_COUNTS.get() is counts
        raise failure
    with pytest.raises(type(failure)) as caught:
        await verifier.routed(operation, counts, True)
    assert caught.value is failure
    assert (USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get()) == previous


def test_cli_does_not_claim_random_stock_sampling(verifier):
    args = importlib.import_module("verify_foundation_sources").parser().parse_args(['--test-mysql-settings', 'private.json', '--output', 'build/new.json', '--proxy-only'])
    assert args.random_count == 0 and args.seed is None
    assert args.kinds == ['sina', 'ths', 'calendar', 'suspensions']
