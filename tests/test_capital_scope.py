"""Exact scope counterexamples, including retained historical unknowns."""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.parser import parse
from empire.features.capital_actions.preparation import inspect_unit, temporal
from tests.capital_samples import source


def inputs():
    rows, _ = parse('dividends', source('dividends'), 10000, '2025-12-31')
    stored = [dict(record_key=r['record_key'], market=r['market'], code=r['code'], name=r['name'],
        event_date=date.fromisoformat(r['event_date']), payload=r['data'], content_hash=digest(r)) for r in rows]
    state = dict(contract_version=3, units={'SH:688110':dict(count=len(rows), digest=digest(rows),
        observed_at=datetime.now(UTC).isoformat()), 'SZ:001228':dict(count=1, digest='unknown')})
    return stored, state


def test_proven_empty_date_projection_ignores_other_security_unknown():
    stored, state = inputs()
    original = deepcopy(stored)
    rows, stamp, finding = inspect_unit('dividends', 'SH:688110', stored, state,
        PreparationScope.parse(dict(codes=['688110'], start='2026-07-01', end='2026-07-31')), datetime.now(UTC))
    assert rows == [] and stamp.tzinfo is not None and '范围内 0 条' in finding['message']
    assert digest([]) in finding['message'] and stored == original


@pytest.mark.parametrize('change', ['missing', 'different_key', 'different_content', 'damaged_hash', 'old_contract', 'missing_proof'])
def test_unit_must_match_keys_and_content_before_date_filter(change):
    stored, state = inputs()
    if change == 'missing':
        stored.clear()
    elif change == 'different_key':
        state['units']['SH:688110']['digest'] = digest([{'record_key':'another'}])
    elif change == 'different_content':
        stored[0]['name'] = '修订名称'
    elif change == 'damaged_hash':
        stored[0]['content_hash'] = '0'*64
    elif change == 'old_contract':
        state['contract_version'] = 2
    else:
        state['units'].pop('SH:688110')
    with pytest.raises(ValueError):
        inspect_unit('dividends', 'SH:688110', stored, state,
            PreparationScope.parse(dict(start='2026-07-01')), datetime.now(UTC))


def test_current_revisions_are_never_authorized_as_historical_signals():
    check = temporal(PreparationScope.parse(dict(purpose='historical_signal')))
    assert check.status == 'fail' and check.blocking and check.reason == 'source_limit'
    analysis = temporal(PreparationScope())
    assert analysis.status == 'pass' and not analysis.blocking and '最早预案' in analysis.measured


@pytest.mark.parametrize('case', ['valid','offline','wrong','old','future','pending'])
async def test_scoped_unit_freshness_reuses_exact_optional_cache_and_preserves_negative_evidence(monkeypatch, case):
    from empire.features.capital_actions.preparation import preparation_check
    now = datetime.now(UTC)
    old = now-timedelta(days=4)
    checks = tuple(CheckEvidence(k,'fail' if k=='freshness' else 'pass','matched',observed_at=old.isoformat())
        for k in ('fields','keys','coverage','quality','freshness','temporal'))
    verified = {'SH:688110':('1'*64,old)}
    stamp = now+timedelta(days=1) if case=='future' else old-timedelta(days=1) if case=='old' else now
    proofs = {'SH:688110':dict(hash='0'*64 if case=='wrong' else '1'*64,
        version=[stamp.isoformat(timespec='microseconds')])}
    monkeypatch.setattr('empire.plugins.pipeline.fingerprints.FingerprintCache.peek',AsyncMock(return_value=proofs))
    client = SimpleNamespace(hget=AsyncMock(return_value='{"phase":"fetch","scope_changed":true}' if case=='pending' else '{}'))
    store=SimpleNamespace(prefix='unit-test',client=client)
    plugin=SimpleNamespace(mysql=SimpleNamespace(read=AsyncMock(return_value=(checks,verified,{}))),
        kind='dividends',source='tdx',job_key='tdx-dividends-v1',archive_settings={},
        context=SimpleNamespace(optional=lambda _:None if case=='offline' else store))
    result={c.criterion:c for c in await preparation_check(plugin,PreparationScope())}
    assert result['freshness'].status == ('pass' if case=='valid' else 'fail')
    assert result['coverage'].status == ('fail' if case=='pending' else 'pass')


def test_preparation_outcomes_separate_failure_source_limit_and_unchecked():
    from empire.features.preparation.results import summarize
    item=dict(id='temporal',phase='数据',status='unknown',blocking=True)
    assert summarize([item])['outcome']=='未检查'
    assert summarize([dict(item,status='fail')])['outcome']=='检查失败'
    assert summarize([dict(item,reason='query_error')])['outcome']=='检查失败'
    assert summarize([dict(item,status='fail',reason='source_limit')])['outcome']=='来源受限'
    assert summarize([dict(item,status='pass')])['outcome']=='通过'
