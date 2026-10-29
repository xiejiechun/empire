from datetime import date, timedelta

import pytest

from empire.features.market_review.model import DOWN, OPEN, UP, summarize, theme_window


async def test_health_snapshot_before_start_running_and_after_stop():
    from types import SimpleNamespace

    from empire.bootstrap import build_manager
    manager = build_manager({'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}})
    plugin = manager.entries['data.market_review'].plugin
    def status():
        return next(p for p in manager.snapshot()['plugins'] if p['id'] == 'data.market_review')
    assert status()['health']['status'] == 'stopped'
    await plugin.start(SimpleNamespace(get=lambda _: object()))
    assert plugin.health() == {'status': 'ok'}
    assert not status()['error']
    await plugin.stop()
    assert plugin.health() == {'status': 'stopped'}


def sample(day, codes, pool=UP):
    return (dict(trade_date=day, pool_type=pool, source_total=len(codes)),
            [dict(trade_date=day, pool_type=pool, unified_code=c, name=c,
                  high_days='4天2板', change_rate=10) for c in codes])


def run(sets):
    heads, members = [], []
    days = [date(2026, 10, n) for n in (22, 23, 26, 27, 28)][:len(sets)]
    for day, codes in zip(days, sets):
        if codes is not None:
            h, m = sample(day, codes)
            heads.append(h)
            members.extend(m)
    return summarize(days, heads, members, [], days[0])['days']


def test_streaks_cross_weekend_but_not_missing_pool_and_ignore_source_label():
    result = run([[], ['A', 'B'], ['A', 'B'], None, ['A', 'C']])
    assert result[1]['height'] == 1  # 4天2板 is not a continuous streak
    assert result[2]['height'] == 2 and len(result[2]['leaders']) == 2
    assert result[2]['first_promotion'] == 100
    assert result[3]['up'] is None
    assert result[4]['height'] is None and result[4]['chain'] is None


def test_left_censoring_recovers_only_after_observed_nonmembership():
    result = run([['A'], ['A', 'B'], ['B'], ['A', 'B']])
    assert result[0]['height'] is None and result[1]['height'] is None
    assert result[2]['height'] == 2 and result[3]['height'] == 3
    assert result[3]['promotion'] == 100


def test_empty_pool_is_not_missing_and_zero_denominators_are_unknown():
    result = run([[], [], None])
    assert result[0]['up'] == 0 and result[0]['height'] == 0
    assert result[1]['first_promotion'] is None and result[1]['promotion'] is None
    assert result[2]['up'] is None


def test_sealed_ratio_uses_union_and_rejects_incomplete_members():
    day = date(2026, 10, 23)
    records = [sample(day, ['A', 'B']), sample(day, ['B', 'C'], OPEN), sample(day, ['D'], DOWN)]
    heads = [h for h, _ in records]
    members = [r for _, ms in records[:2] for r in ms]
    result = summarize([day], heads, members, [], day)['days'][0]
    assert result['sealed'] == pytest.approx(200 / 3)
    with pytest.raises(ValueError, match='成员'):
        summarize([day], heads, members[:-1], [], day)


def test_theme_window_missing_days_not_zero_and_identity_not_name():
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(10)]
    data = {d: [dict(theme_id='A', name='改名' if i == 9 else '旧名', hot_score=10,
                    parent_id=None)] for i, d in enumerate(days)}
    rows, count = theme_window(data, days)
    assert rows == [dict(theme_id='A', name='改名', heat=100)] and count == 10
    del data[days[4]]
    assert theme_window(data, days) == ([], 9)
