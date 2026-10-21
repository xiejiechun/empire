from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.features.suspensions.coverage import confirmed_coverage, coverage_as_of
from empire.plugins.pipeline.fingerprints import digest


@pytest.mark.parametrize('case', ['valid', 'missing', 'wrong', 'future', 'old', 'offline', 'error', 'different_range'])
async def test_optional_time_proof_never_extends_dates_or_bypasses_sql(monkeypatch, case):
    coverage = {'from':'2004-12-27','through':'2026-10-21','confirmed_at':'2026-10-21T13:40:00+08:00'}
    key = 'coverage:2026-10-21:2026-10-21'
    stamp = ('2026-10-22T08:00:00.000000+00:00' if case == 'future' else
             '2026-10-21T02:00:00.000000+00:00' if case == 'old' else '2026-10-21T08:00:00.000000+00:00')
    proofs = {key:dict(hash=digest({'checked_dates':['2026-10-21']}),version=[stamp])}
    if case == 'wrong':
        proofs[key]['hash'] = '0'*64
    if case == 'different_range':
        proofs = {'coverage:2026-10-20:2026-10-22':proofs[key]}
    peek = AsyncMock(return_value={} if case == 'missing' else proofs)
    if case == 'error':
        peek.side_effect = ConnectionError('private')
    monkeypatch.setattr('empire.plugins.pipeline.fingerprints.FingerprintCache.peek', peek)
    now = datetime(2026,10,21,18,tzinfo=CHINA)
    actual = await confirmed_coverage(coverage,None if case == 'offline' else SimpleNamespace(),{},now)
    assert actual['from'] == coverage['from'] and actual['through'] == coverage['through']
    assert coverage['confirmed_at'] == '2026-10-21T13:40:00+08:00'
    assert coverage_as_of(actual,now,now.replace(hour=15,minute=30))[0] == ('pass' if case == 'valid' else 'fail')


async def test_sql_post_close_evidence_survives_redis_offline():
    coverage = {'from':'2004-12-27','through':'2026-10-21','confirmed_at':'2026-10-21T16:00:00+08:00'}
    now=datetime(2026,10,21,18,tzinfo=CHINA)
    assert await confirmed_coverage(coverage,None,{},now) == coverage
    assert coverage_as_of(coverage,now,now.replace(hour=15,minute=30))[0] == 'pass'
