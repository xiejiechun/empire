import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.plugins.data.calendar_preparation import check_calendar, merge_confirmations
from empire.plugins.data.preparation_checks import audit_calendar
from empire.plugins.datasets.trade_calendar import month_dates, months_between
from empire.plugins.pipeline.fingerprints import digest


def sample():
    now = datetime.now(CHINA)
    months = months_between(now.strftime('%Y-%m'), f'{now.year + 1}-12')
    rows = [{'trade_date': d, 'is_trade': 1} for m in months for d in month_dates(m)]
    state = {'observed': {m: (now - timedelta(days=4)).isoformat() for m in months}}
    proofs = {m: {'hash': digest([{'trade_date': d.isoformat(), 'is_trade': True} for d in month_dates(m)]),
                  'version': [now.astimezone(UTC).isoformat(timespec='microseconds')]} for m in months}
    return now, months, rows, state, proofs


def test_current_cache_proves_freshness_without_mutating_sql_state():
    now, months, rows, state, proofs = sample()
    before = copy.deepcopy(state)
    combined, accepted = merge_confirmations(rows, state, proofs, now)
    result = {c.criterion: c for c in audit_calendar(rows, combined, now, cache_months=accepted)}
    assert state == before and accepted == months
    assert result['freshness'].status == result['temporal'].status == 'pass'
    assert result['coverage'].status == 'fail'  # Fresh cache cannot conceal missing history.


@pytest.mark.parametrize('damage', ['hash', 'future', 'naive', 'old', 'missing_day', 'duplicate', 'invalid_flag'])
def test_bad_cache_or_month_cannot_replace_sql_evidence(damage):
    now, months, rows, state, proofs = sample()
    month = months[0]
    if damage == 'hash':
        proofs[month]['hash'] = '0' * 64
    elif damage in ('future', 'old', 'naive'):
        stamp = now + timedelta(days=1) if damage == 'future' else now - timedelta(days=5)
        proofs[month]['version'] = [stamp.replace(tzinfo=None).isoformat() if damage == 'naive'
                                    else stamp.astimezone(UTC).isoformat(timespec='microseconds')]
    elif damage == 'missing_day':
        rows.pop(0)
    elif damage == 'duplicate':
        rows.append(rows[0])
    else:
        rows[0]['is_trade'] = 2
    combined, accepted = merge_confirmations(rows, state, proofs, now)
    assert month not in accepted and combined['observed'][month] == state['observed'][month]


def test_bad_sql_observation_is_not_hidden_by_cache():
    now, months, rows, state, proofs = sample()
    state['observed'][months[0]] = 'broken'
    combined, accepted = merge_confirmations(rows, state, proofs, now)
    assert months[0] not in accepted
    assert next(c for c in audit_calendar(rows, combined, now) if c.criterion == 'freshness').status == 'fail'


@pytest.mark.parametrize('cache_state', ['offline', 'error', 'missing', 'valid'])
@pytest.mark.parametrize('sql_recent', [True, False])
async def test_optional_cache_falls_back_to_sql(monkeypatch, cache_state, sql_recent):
    now, months, rows, state, proofs = sample()
    if sql_recent:
        state['observed'] = {m: now.isoformat() for m in months}
    reader = AsyncMock(return_value=proofs if cache_state == 'valid' else {})
    if cache_state == 'error':
        reader.side_effect = ConnectionError('secret must not escape')
    monkeypatch.setattr('empire.plugins.pipeline.fingerprints.FingerprintCache.peek', reader)
    store = SimpleNamespace(prefix='test', client=None)
    plugin = SimpleNamespace(mysql=SimpleNamespace(read=AsyncMock(return_value=(rows, state))),
        context=SimpleNamespace(optional=lambda _: None if cache_state == 'offline' else store),
        archive_settings={}, source='test')
    result = {c.criterion: c for c in await check_calendar(plugin)}
    assert result['freshness'].status == ('pass' if sql_recent or cache_state == 'valid' else 'unknown')
    assert 'secret' not in str(result)
    assert plugin.mysql.read.await_count == 1
