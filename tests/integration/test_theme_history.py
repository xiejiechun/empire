"""Real Redis in a UUID namespace; never edits shared application history."""
import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from empire.core.config import load_config
from empire.features.themes.history import ThemeHistory
from empire.features.themes.history_model import BEIJING, HistoryError, expiry
from empire.plugins.infra.redis_store import create_client

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='requires isolated Redis')]


def row(key='1', **changes):
    return dict(theme_id=key, name='题材' + key, parent_id=None, rank_no=1,
                display_order=0, hot_score='100', change_rate='1.2', limit_up_count=2,
                source_theme_id=key, concept_id=None, new_flag=0) | changes


@pytest_asyncio.fixture
async def store():
    cfg = load_config()
    client = create_client(cfg['redis'])
    prefix = 'empire:test:theme:' + uuid4().hex
    history = ThemeHistory(client, prefix)
    today = datetime.now(BEIJING).date()
    now = datetime.combine(today, datetime.min.time(), BEIJING) + timedelta(hours=12)
    history._now = AsyncMock(return_value=now)
    try:
        yield history, now
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + ':*')]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def append(history, now, number, rows=None):
    return await history.append(rows or [row()], observed_at=now + timedelta(seconds=number),
                                round_id=str(number))


@pytest.mark.asyncio
async def test_child_missing_metrics_and_exact_ratio_survive_delta_replay(store):
    history, now = store
    child = row('1_7', source_theme_id='1', concept_id='7', parent_id='1',
                hot_score=None, rank_no=None, change_rate='0.100000001490116119384765625')
    await append(history, now, 0, [row(), child])
    await append(history, now, 1, [row(), child | {'limit_up_count': 5}])
    replay = await history.snapshot(now.date())
    found = next(r for r in replay['rows'] if r['concept_id'] == '7')
    assert found['hot_score'] is None and found['rank_no'] is None
    assert found['change_rate'] == child['change_rate'] and found['limit_up_count'] == 5


@pytest.mark.asyncio
async def test_baseline_delta_nochange_replay_and_exact_time(store):
    history, now = store
    await append(history, now, 0)
    await append(history, now, 1, [row(rank_no=3, limit_up_count=0), row('2')])
    await append(history, now, 2, [row(rank_no=3, limit_up_count=0), row('2')])
    assert (await append(history, now, 1, [row(rank_no=3, limit_up_count=0), row('2')]))['replayed']
    old = await history.snapshot(now.date(), at=now)
    assert len(old['rows']) == 1 and old['rows'][0]['rank_no'] == 1
    latest = await history.snapshot(now.date())
    assert latest['round_id'] == '2' and len(latest['rows']) == 2
    events = await history.redis.hgetall(history.keys(now.date())[3])
    assert json.loads(events['1'])['change']['changed'] == {'1': {'rank_no': 3, 'limit_up_count': 0}}
    assert json.loads(events['2'])['change'] is None
    assert all('rows' not in json.loads(value) for value in events.values())
    assert await history.snapshot(now.date(), at=now - timedelta(seconds=1)) is None
    with pytest.raises(HistoryError, match='轮次ID'):
        await append(history, now, 1, [row(rank_no=9)])


@pytest.mark.asyncio
async def test_older_and_capacity_rejection_leave_all_keys_unchanged(store):
    history, now = store
    await append(history, now, 1)
    keys = history.keys(now.date())
    before = [await history.redis.dump(key) for key in keys]
    with pytest.raises(HistoryError, match='迟到'):
        await append(history, now, 0)
    history.max_rounds = 1
    with pytest.raises(HistoryError, match='容量'):
        await append(history, now, 2, [row(rank_no=2)])
    assert before == [await history.redis.dump(key) for key in keys]
    history.max_rounds = 10
    history.max_day_bytes = 1
    with pytest.raises(HistoryError, match='容量'):
        await append(history, now, 2)
    assert before == [await history.redis.dump(key) for key in keys]


@pytest.mark.asyncio
async def test_daily_independence_and_seven_calendar_days(store):
    history, now = store
    for offset in (6, 1, 0):
        observed = now - timedelta(days=offset)
        history._now.return_value = observed
        await history.append([row(name=f'第{offset}天')], observed_at=observed, round_id=f'day{offset}')
        keys = history.keys(observed.date())
        for key in keys[1:]:
            assert await history.redis.expiretime(key) == expiry(observed.date())
    history._now.return_value = now
    assert (await history.snapshot((now - timedelta(days=6)).date()))['rows'][0]['name'] == '第6天'
    with pytest.raises(HistoryError, match='七个自然日'):
        await history.snapshot((now - timedelta(days=7)).date())
    await history.redis.delete(*history.keys((now - timedelta(days=6)).date())[1:])
    assert (await history.snapshot(now.date()))['rows'][0]['name'] == '第0天'


@pytest.mark.asyncio
async def test_corrupt_or_missing_event_is_never_a_valid_snapshot(store):
    history, now = store
    await append(history, now, 0)
    await append(history, now, 1, [row(rank_no=2)])
    await history.redis.hdel(history.keys(now.date())[3], '0')
    with pytest.raises(HistoryError):
        await history.snapshot(now.date())
    with pytest.raises(HistoryError):
        await append(history, now, 2)


@pytest.mark.asyncio
async def test_restart_loses_history_not_fabricated_and_competing_writers(store):
    history, now = store
    for attempt in range(10):
        early, late = 2 * attempt, 2 * attempt + 1
        results = await asyncio.gather(
            append(history, now, early), append(history, now, late, [row(rank_no=7)]),
            return_exceptions=True)
        assert not all(isinstance(value, Exception) for value in results)
        assert (await history.snapshot(now.date()))['rows'][0]['rank_no'] == 7, results
    await history.redis.delete(*history.keys(now.date()))
    assert await history.snapshot(now.date()) is None
    await append(history, now, 2, [row(rank_no=8)])
    assert await history.snapshot(now.date(), at=now) is None
    assert (await history.snapshot(now.date()))['round_id'] == '2'


@pytest.mark.asyncio
async def test_tampered_delta_and_base_refuse_replay(store):
    history, now = store
    await append(history, now, 0)
    await append(history, now, 1, [row(rank_no=2)])
    keys = history.keys(now.date())
    raw = await history.redis.hget(keys[3], '1')
    event = json.loads(raw)
    event['change']['changed']['1']['rank_no'] = 8
    await history.redis.hset(keys[3], '1', json.dumps(event))
    with pytest.raises(HistoryError):
        await history.snapshot(now.date())
    await history.redis.hset(keys[3], '1', raw)
    base = json.loads(await history.redis.get(keys[1]))
    base['rows']['1']['name'] = '外部修改'
    await history.redis.set(keys[1], json.dumps(base))
    with pytest.raises(HistoryError):
        await history.snapshot(now.date())
