"""Scheduling, revision boundaries and SQL recovery use the seven formal collectors."""
from datetime import date, datetime

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.kaipanla.contract import PRODUCTS, project
from empire.features.kaipanla.refresh import review_days, review_token
from scripts.configure_kaipanla_task_defaults import task_plan
from tests.test_kaipanla_products import product_collector


def test_recommended_defaults_and_explicit_configuration_preserve_business_choices():
    definitions = build_manager(load_config()).entries['collection.control'].plugin.definitions
    original = dict(mode='interval', enabled=True, interval_seconds=1,
                    daily_time='09:00', request_retries=3, use_proxy=False, proxy_fallback=False)
    plan = task_plan({'kaipanla-quote': original})
    for kind in PRODUCTS:
        policy = plan[project(kind)]
        assert definitions[project(kind)].default_schedule.policy(policy) == policy
        assert policy['mode'] == 'daily' and policy['daily_time'] == '18:00'
        assert policy['enabled'] is (kind == 'quote')
    assert plan['kaipanla-quote']['request_retries'] == 3
    assert plan['kaipanla-quote']['use_proxy'] is False
    assert plan['kaipanla-quote']['proxy_fallback'] is False
    assert task_plan(plan) == plan


def test_weekly_review_friday_boundary_and_year_change():
    assert review_token(datetime(2026, 10, 2, 17, 59, tzinfo=CHINA)) == '2026-09-25'
    assert review_token(datetime(2026, 10, 2, 18, tzinfo=CHINA)) == '2026-10-02'
    assert review_token(datetime(2026, 10, 5, 18, tzinfo=CHINA)) == '2026-10-02'
    assert review_token(datetime(2027, 1, 1, 18, tzinfo=CHINA)) == '2027-01-01'
    days = [date(2026, 9, d) for d in range(21, 30)]
    now = datetime(2026, 10, 5, 18, tzinfo=CHINA)
    assert review_days(days, '2026-09-25', now)[1] == [d.isoformat() for d in days[-5:]]
    assert review_days(days, '2026-10-02', now)[1] == []


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_repeated_day_skips_quotes_but_recovers_middle_hole(kind):
    days = [date(2021, 1, d) for d in range(4, 12)]
    c = product_collector(kind, days)
    c.query.covered_days.return_value = set(days)
    first = await c.execute()
    assert len(c.ingest.published) == 5  # Lost Redis review proof is conservatively rebuilt.
    assert first['last_review'] == first['review_token']
    c.ingest.published.clear()
    c.http.request.reset_mock()
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.ingest.published == []
    assert not any('longhuvip' in call.args[1] for call in c.http.request.call_args_list)
    c.query.covered_days.return_value = set(days) - {days[1]}
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert [e.raw_payload['rows'][0]['trade_date'] for e in c.ingest.published] == [days[1].isoformat()]


async def test_failed_review_and_delayed_archive_do_not_mark_review_complete():
    c = product_collector('quote')
    c.query.covered_days.return_value = {date(2021, 1, 4), date(2021, 1, 5)}
    original = c.http.request.side_effect
    async def request(method, url, **kwargs):
        if 'longhuvip' in url and kwargs['attempt_options']()['data']['Day'] == '2021-01-04':
            import httpx
            return httpx.Response(200, json={'errcode': '1017'})
        return await original(method, url, **kwargs)
    c.http.request.side_effect = request
    with pytest.raises(ValueError):
        await c.execute()
    assert c.ingest.state['cursor']['last_review'] is None
    assert c.ingest.state['cursor']['index'] == 0
    c.http.request.side_effect = original
    result = await c.execute(baseline_revision=c.ingest.state['revision'])
    assert result['last_review'] == result['review_token']


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_new_day_extends_plan_without_repeating_existing_days(kind):
    days = [date(2021, 1, 4), date(2021, 1, 5)]
    c = product_collector(kind, days)
    await c.execute()
    c.ingest.published.clear()
    c.query.covered_days.return_value = set(days)
    c.query.plan.return_value = (c.query.plan.return_value[0], days + [date(2021, 1, 6)])
    result = await c.execute(baseline_revision=c.ingest.state['revision'])
    assert result['phase'] == 'complete'
    assert [e.raw_payload['rows'][0]['trade_date'] for e in c.ingest.published] == ['2021-01-06']
