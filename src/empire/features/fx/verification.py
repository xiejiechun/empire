"""Verify daily history against the chart's native dated current candle."""
from empire.features.fx.contract import digest, url, validate_rows
from empire.features.fx.source import closed_through
from empire.plugins.collectors.support import record_error_safely


class FxSourceConflict(ValueError):
    """Valid daily responses disagree; this symbol needs a later source refresh."""


def agrees(snapshot, current, observed):
    latest = snapshot['source_tail'][-1]
    if latest[0] != current[0] or latest[1] != current[1]:
        return False
    # Intraday prices move between necessary responses and are never archived.
    return current[0] > closed_through(observed) or latest == current


def reconcile(snapshot, annual_rows, observed, current):
    """Account for the separately dated active row; never allow a count tolerance."""
    cutoff = closed_through(observed)
    active_day = current[0] > cutoff
    latest = snapshot['source_tail'][-1]
    if latest[0] > current[0] or latest[0] == current[0] and latest[1] != current[1]:
        raise ValueError('汇率近期与当日日线日期/开盘不一致，保留原数据')
    closed = {}
    counts = dict(snapshot['years'])
    recent = {row[0]: row for row in snapshot['rows']}
    for year, raw in annual_rows.items():
        validate_rows(raw, year)
        rows = [row for row in raw if row[0] <= cutoff]
        count = snapshot['source_years'].get(str(year))
        native_year = year == int(current[0][:4]) and active_day
        contains_current = raw[-1][0] == current[0]
        # Official daily history and today's row are separate. The directory
        # may reserve that exact active row before it appears in either body.
        reserved = (native_year and count == len(raw) + 1 and not contains_current
                    and raw[-1][0] == snapshot['source_tail'][-1][0]
                    and raw[-1][0] < current[0])
        extension = (native_year and count == len(raw) - 1 and contains_current
                     and len(raw) >= 2 and raw[-2][0] == snapshot['source_tail'][-1][0]
                     and current[0] > snapshot['source_tail'][-1][0])
        incomplete = (count is not None and len(raw) != count and not (reserved or extension)
                      or count is None and bool(rows))
        wrong_start = rows and year == int(snapshot['start'][:4]) and rows[0][0] != snapshot['start']
        if incomplete or wrong_start or raw[-1][0] > current[0]:
            raise ValueError(f'汇率核验年度与来源目录不完整（{year}: {len(raw)}/{count}），保留原数据')
        by_date = {row[0]: row for row in rows}
        expected = {day: row for day, row in recent.items() if int(day[:4]) == year}
        if not expected.keys() <= by_date.keys():
            raise ValueError('汇率年度与近期日期集合不一致，保留原数据')
        if any(by_date[day] != row for day, row in expected.items()):
            raise ValueError('汇率近期与年度已结束日线内容不一致，保留原数据')
        if contains_current and (raw[-1][1] != current[1] or not active_day and raw[-1] != current):
            raise ValueError('汇率年度与当日日线内容不一致，保留原数据')
        closed[year] = rows
        if rows:
            counts[str(year)] = len(rows)
        else:
            counts.pop(str(year), None)
    values = {day: row for day, row in recent.items() if int(day[:4]) not in closed}
    values.update((row[0], row) for rows in closed.values() for row in rows)
    rows = [values[day] for day in sorted(values)]
    if not rows:
        raise ValueError('汇率核验未取得已结束日线')
    # The unclosed native row proves directory membership, not a historical
    # price: keep it only in the in-memory verification tail, never in rows.
    source_tail = [rows[-1], current] if active_day else rows[-2:]
    return {**snapshot, 'rows': rows, 'end': rows[-1][0], 'years': counts,
            'source_tail': source_tail}, {
                year: validate_rows(values, year) for year, values in closed.items() if values}


async def verified_snapshot(collector, code):
    snapshot, observed = await collector.fetch(code)
    current = await collector.fetch(code, 'today')
    if agrees(snapshot, current, observed):
        return snapshot, observed, {}
    years = sorted({int(current[0][:4]), int(snapshot['end'][:4])})
    candidates = {year: await collector.fetch(code, year, raw_annual=True) for year in years}
    try:
        resolved, verified = reconcile(snapshot, candidates, observed, current)
        if not agrees(resolved, current, observed):
            raise ValueError('汇率近期、年度与当日日线日期/内容不一致，本轮保留原数据')
    except ValueError as cause:
        exc = FxSourceConflict(f'{code}: {cause}')
        exc.diagnostic_recorded = await record_error_safely(collector.records, collector.stats,
            collector.project_id, exc, stage='source_validation',
            unavailable_message='汇率跨响应核验诊断暂不可用', fields=dict(request_url=url(code),
                metadata=dict(kind='cross_response_validation', symbol=code,
                    cutoff=closed_through(observed), source_tail=snapshot['source_tail'],
                    current_candle=current, annuals={str(year): dict(directory=snapshot['source_years'].get(str(year)),
                        count=len(rows), first=rows[0][0] if rows else None,
                        tail=[' | '.join(row) for row in rows[-3:]],
                        content_sha256=digest(rows), dates_sha256=digest([r[0] for r in rows]))
                        for year, rows in candidates.items()})))
        raise exc from cause
    collector.stats['reconciled_years'] = years
    return resolved, observed, verified
