"""Business-owned calendar.audit_rules."""
from collections import Counter

from empire.contracts.preparation import CheckEvidence
from empire.features.calendar.contract import FIRST_DATE, month_dates, months_between
from empire.features.preparation.evidence import evidence, freshness


def audit_calendar(rows, state, now, *, cache_months=(), cache_note='未读取 Redis 缓存确认'):
    end = f'{now.year + 1}-12'
    months = months_between('1990-12', end)
    expected = {d for month in months for d in month_dates(month)}
    valid = {r['trade_date'] for r in rows if r['is_trade'] in (0, 1)}
    invalid = [r['trade_date'] for r in rows if r['is_trade'] not in (0, 1) or r['trade_date'] < FIRST_DATE]
    missing = expected - valid
    missing_months = Counter(day.strftime('%Y-%m') for day in missing)
    duplicates = len(rows) - len({r['trade_date'] for r in rows})
    observed = state.get('observed', {})
    active = [m for m in months if m >= now.strftime('%Y-%m')]
    stamps = [freshness(observed.get(m), now, m) for m in active]
    stale = [m for m, stamp in zip(active, stamps, strict=True) if stamp.status != 'pass']
    invalid_stamps = [m for m, stamp in zip(active, stamps, strict=True) if stamp.status == 'fail']
    return (
        evidence('fields', bool(rows) and not invalid, f'逐行核验日期与 0/1 标记；无效 {len(invalid)}'),
        evidence('keys', bool(rows) and not duplicates, f'trade_date 重复 {duplicates}'),
        evidence('coverage', not missing and len(rows) < 20001,
                 f'目标 {FIRST_DATE} 至 {end}-31，共 {len(expected)} 天；缺 {len(missing)} 天；'
                 f'缺失月份及天数：{dict(sorted(missing_months.items()))}'),
        evidence('quality', bool(rows) and not invalid and not duplicates,
                 f'非法标记/起点前日期 {len(invalid)}；重复 {duplicates}；未按周末推断任何记录'),
        CheckEvidence('freshness', 'fail' if invalid_stamps else 'unknown' if stale else 'pass',
                      f'当前维护区间 {len(active)} 月；可信 Redis 确认 {len(cache_months)} 月；'
                      f'无法证明近 3 天确认的月份 {stale}；异常时间 {invalid_stamps}；{cache_note}；'
                      '其余依据 SQL 确认，不把 SQL 旧上界直接认定停更'),
        CheckEvidence('temporal', 'unknown' if stale else 'pass',
                      '未来安排按当前来源保存，可修订；逐月确认时间' + ('尚缺有效证据' if stale else '有效且不超前')),
    )
