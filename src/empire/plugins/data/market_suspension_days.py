"""Conservative trading-day exclusions from preserved source event identities."""

import re
from datetime import time, timedelta

WHOLE_DAY_NOTE = re.compile(r'今起停牌|连续停牌|继续停牌|全天停牌|停牌\s*(?:[一二三四五六七八九十\d]+\s*天)')


def excluded_days(rows, wanted, start, end):
    result = {key: set() for key in wanted}
    groups, counts = {}, {}
    for row in rows:
        key = row['unified_code']
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 1000:
            raise ValueError('单证券停牌生命周期证据超过上限')
        groups.setdefault((key, row['suspended_at']), []).append(row)
    for (key, suspended), events in groups.items():
        full = [row for row in events if row['suspension_type'] == 'full_day']
        if not full:
            continue
        lower = suspended.date()
        if suspended.time() > time(9, 30):
            lower += timedelta(days=1)
        resumes = [row['resumed_at'] for row in events
                   if row['resumed_at'] and row['resumed_at'] >= suspended]
        if resumes:
            # Preserve conflicting source records, but never exclude beyond
            # their earliest explicit resumption (including intraday records).
            upper = min(resumes).date()
        elif (lower == suspended.date() and any(
                WHOLE_DAY_NOTE.search(row['source_note']) for row in full)):
            # An explicit whole-day start proves this day only. Unknown resume
            # cannot prove subsequent days, even with a later calendar appearance.
            upper = lower + timedelta(days=1)
        else:
            continue
        day = max(lower, start)
        while day < upper and day <= end:
            result[key].add(day)
            day += timedelta(days=1)
    return result
