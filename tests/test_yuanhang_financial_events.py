"""Full-pool financial counterexamples; preserve events and explicit unknowns."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from empire.features.adjustment.contract import calculate, ex_reference
from empire.features.capital_actions.event_rules import ActionError
from empire.sources.yuanhang_coverage import financial_proofs
from empire.sources.yuanhang_history import normalize_financial
from empire.sources.yuanhang_payload import action_key, financial_payload, validate_financial
from tests.test_yuanhang_history import action, tables
from tests.test_yuanhang_payload import CODE, snapshot


def source(actions=None):
    security = 'USHT' + CODE[:6]
    result = tables([{1: 19970101, 402: 100., 407: 80.}, {1: 20200101, 402: 120., 407: None}], security)
    result += tables([{1: 19970101, 380: 70.}], security)
    result += tables(actions or [action(20240627, **{'454': .3, '460': .3, '463': .5}),
        action(20240627, **{'454': 0., '460': 0., '463': .16})], security)
    return result


def normalized(t=None):
    return normalize_financial(t or source(), unified_code=CODE, start=date(1900,1,1),
                              end=date(2100,12,31), native_market='USHT')


def payload(t=None):
    return financial_payload(snapshot(normalized(t)), code=CODE)


@pytest.mark.parametrize(('when', 'first', 'second'), [
    (19971103, {454: .4, 460: .1, 463: 0.}, {454: .4, 460: 0., 463: 0.}),
    (19980922, {454: .1, 460: 0., 463: 0.}, {454: 0., 460: 0., 463: .2}),
    (20240627, {454: .3, 460: .3, 463: .5}, {454: 0., 460: 0., 463: .16}),
])
def test_same_day_different_events_survive_and_source_tie_order_is_irrelevant(when, first, second):
    rows = [action(when, **{str(k): v for k,v in r.items()}) for r in (first,second)]
    p = payload(source(rows))
    assert len(p['actions']) == 2 and len({action_key(r) for r in p['actions']}) == 2
    assert p == payload(source(list(reversed(rows))))
    assert financial_proofs(p)['actions']['row_count'] == 2


@pytest.mark.parametrize('ratio', ['-0.67335', '-0.87581'])
def test_verified_pure_consolidation_is_preserved_and_adjusted(ratio):
    p = payload(source([action(20070330, **{'454': Decimal(ratio), '460': 0., '463': 0.})]))
    assert p['actions'][0][1] == ratio
    reference = ex_reference('10', '0', ratio, '0', '0')
    assert abs(reference * (1 + Decimal(ratio)) - 10) < Decimal('1e-26')
    raw = [dict(date=day, **dict.fromkeys(('open','high','low','close'), '10'))
           for day in ('2007-03-29','2007-03-30')]
    assert Decimal(calculate(raw,p['actions'])[-1]['factor']) < 1


@pytest.mark.parametrize('bad', ['-1', '-2', 'NaN', 'Infinity'])
def test_invalid_consolidation_cannot_enter_calculation(bad):
    with pytest.raises(ActionError):
        ex_reference('10','0',bad,'0','0')


def test_explicit_circulating_null_keeps_its_date_and_other_kinds_cannot_be_null():
    p = payload()
    assert p['capital'][:2] == [['circulating','1997-01-01','80'],['circulating','2020-01-01',None]]
    for index in (2,3):
        bad = deepcopy(p)
        bad['capital'][index][2] = None
        with pytest.raises(ValueError):
            validate_financial(bad)


def test_duplicate_full_event_and_descending_source_dates_still_fail():
    with pytest.raises(ValueError, match='重复'):
        payload(source([action(),action()]))
    with pytest.raises(ValueError, match='unordered'):
        payload(source([action(20240627),action(20230627)]))


def test_same_date_partial_field_tables_are_ambiguous_and_cannot_be_joined():
    t = source()[:2]
    security = 'USHT' + CODE[:6]
    t += tables([{1: 20240627, 454: .3}, {1: 20240627, 454: .1}], security)
    t += tables([{1: 20240627, 455: 0., 456: 0., 460: .3, 463: .5}], security)
    with pytest.raises(ValueError, match='unordered'):
        normalized(t)


def test_same_day_events_are_facts_but_not_an_automatic_adjustment_decision():
    p = payload()
    raw = [dict(date=day, **dict.fromkeys(('open','high','low','close'), '10'))
           for day in ('2024-06-26','2024-06-27')]
    with pytest.raises(ActionError, match='同日') as error:
        calculate(raw, p['actions'])
    assert error.value.day == '2024-06-27'
