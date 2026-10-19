from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.query import CapitalDataPlugin


@pytest.mark.parametrize('sql_recent', [True, False])
@pytest.mark.parametrize('proof_state', ['valid', 'missing', 'wrong', 'future', 'old', 'offline', 'error'])
async def test_optional_freshness_proof_preserves_sql_fallback(monkeypatch, sql_recent, proof_state):
    now = datetime.now(UTC)
    observed = now - timedelta(days=1 if sql_recent else 4)
    actual = dict(units=1, count=1, scope_hash='scope', digest='content')
    stamp = now + timedelta(days=1) if proof_state == 'future' else now
    if proof_state == 'old':
        stamp = now - timedelta(days=5)
    proof = {'manifest': {'hash': digest({'rows': [], 'manifest': actual}),
                          'version': [stamp.isoformat()]}}
    if proof_state == 'wrong':
        proof['manifest']['hash'] = '0' * 64
    reader = AsyncMock(return_value={} if proof_state == 'missing' else proof)
    if proof_state == 'error':
        reader.side_effect = ConnectionError('private diagnostic')
    monkeypatch.setattr('empire.plugins.pipeline.fingerprints.FingerprintCache.peek', reader)
    plugin = CapitalDataPlugin('dividends')
    plugin.mysql = SimpleNamespace(read=AsyncMock(return_value=(actual, True, sql_recent, 'matched', observed)))
    store = SimpleNamespace(prefix='test', client=None)
    plugin.context = SimpleNamespace(optional=lambda _: None if proof_state == 'offline' else store)
    checks = {c.criterion: c for c in await plugin.preparation_check()}
    assert checks['freshness'].status == ('pass' if sql_recent or proof_state == 'valid' else 'fail')
    assert 'private diagnostic' not in str(checks)
