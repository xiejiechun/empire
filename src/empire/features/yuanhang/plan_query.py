"""Read-only planning from SQL coverage, without historical fact scans."""
import json
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text

from empire.core.time import CHINA
from empire.features.yuanhang.contract import PRICE_PROJECT
from empire.features.yuanhang.planning import (
    DailyPlan,
    PlanningCalendar,
    calendar_dates,
    plan_daily,
)
from empire.plugins.infra.collection_state_unit import unit_path
from empire.sources.yuanhang_payload import CONTRACT
from empire.sources.yuanhang_ranges import contiguous_through, expand_versions


def coverage_summary(conn, namespace, code):
    raw = conn.execute(text('SELECT JSON_EXTRACT(payload,:path) FROM collection_state '
        'WHERE namespace=:ns AND project_id=:project'),
        dict(path=unit_path(code), ns=namespace, project=PRICE_PROJECT)).scalar_one_or_none()
    unit = json.loads(raw) if isinstance(raw, str) else raw
    if not unit or not unit.get('price_ranges'):
        return dict(through=None, full_checked=None)
    years = sorted(int(y) for y in unit['price_ranges'])
    end = None
    for y in range(years[0], years[-1]+1):
        value = contiguous_through(unit['price_ranges'].get(str(y), []), y)
        if value is None:
            break
        end = value
        if value != f'{y}-12-31':
            break
    checked = [unit.get('full_checked', {}).get(str(y)) for y in years]
    full = min(checked) if all(checked) else None
    return dict(through=end, full_checked=(datetime.fromisoformat(full).astimezone(CHINA).isoformat()
                                        if full else None))


def read_plan_inputs(conn, namespace, codes, force):
    if not 1 <= len(codes) <= 64:
        raise ValueError('远航规划每组须为1至64只证券')
    heads = {code: [] for code in codes}
    statement = text('SELECT unified_code,quote_year,native_market,last_date,contract_version '
        'FROM yuanhang_price_year WHERE unified_code IN :codes '
        'ORDER BY unified_code,quote_year LIMIT :n').bindparams(bindparam('codes', expanding=True))
    for row in conn.execute(statement, dict(codes=codes, n=150 * len(codes) + 1)).mappings():
        heads[row['unified_code']].append(row)
    if any(len(rows) > 150 for rows in heads.values()):
        raise ValueError('远航年度证明超限')
    selected = [code for code in codes if heads[code] and not force]
    units = {}
    if selected:
        params = dict(ns=namespace, project=PRICE_PROJECT)
        columns = []
        for index, code in enumerate(selected):
            params[f'p{index}'] = unit_path(code)
            columns.append(f'JSON_EXTRACT(payload,:p{index}) AS u{index}')
        row = conn.execute(text('SELECT ' + ','.join(columns) + ' FROM collection_state '
            'WHERE namespace=:ns AND project_id=:project'), params).mappings().first()
        for index, code in enumerate(selected):
            raw = row[f'u{index}'] if row else None
            units[code] = json.loads(raw) if isinstance(raw, str) else raw
    return heads, units


def read_plans(conn, namespace, codes, through, *, force=False, scope='all', calendar_cache=None):
    plans = {}
    calendar_cache = calendar_cache if calendar_cache is not None else {}
    calendar = calendar_cache.get('calendar')
    all_heads, units = read_plan_inputs(conn, namespace, codes, force)
    for code in codes:
        heads = all_heads[code]
        if not heads or force:
            plan = DailyPlan(code, 'full', '1900-01-01', through, heads[-1]['native_market'] if heads else None,
                             'explicit_full_verification' if force else 'missing_initial_coverage')
            if not heads and scope == 'recent' and not force:
                plan = DailyPlan(code, 'skip', None, through, None, 'initialization_in_backfill_round')
        else:
            unit = units[code]
            if not unit or 'price_ranges' not in unit:
                raise ValueError('远航已有日线需要显式转换覆盖状态：' + code)
            years = [h['quote_year'] for h in heads]
            earliest = min([*years, *(int(y) for y in unit['price_ranges'])])
            missing = set(range(earliest, int(through[:4]) + 1)) - set(years)
            coverage = None
            for h in heads:
                y = h['quote_year']
                end = contiguous_through(unit['price_ranges'].get(str(y), []), y)
                if h['contract_version'] != CONTRACT or end is None:
                    missing.add(y)
                if end is not None and not any(k < y for k in missing):
                    coverage = end
                    if end != f'{y}-12-31' and y < int(through[:4]):
                        missing.add(y)
            if calendar is None:
                calendar = [(r[0].isoformat(), int(r[1])) for r in conn.execute(text(
                    'SELECT trade_date,is_trade FROM trade_calendar WHERE trade_date BETWEEN '
                    "'1990-12-19' AND :through ORDER BY trade_date LIMIT 54901"), dict(through=through))]
                if not calendar or calendar[0][0] != '1990-12-19':
                    raise ValueError('远航增量规划需要完整正式交易日历起点1990-12-19')
                calendar = PlanningCalendar(calendar, through)
                calendar_cache['calendar'] = calendar
            full = unit.get('full_checked', {})
            checked = [full.get(str(y)) for y in years]
            full_checked = (min(datetime.fromisoformat(v).astimezone(CHINA).date().isoformat() for v in checked)
                            if all(checked) else None)
            # A source request after close can verify an earlier cutoff; cap only the
            # planning date, retaining the actual observation timestamp in state.
            full_checked = min(full_checked, through) if full_checked else None
            latest = max((h['last_date'].isoformat() for h in heads if h['last_date']), default=None)
            gaps = [(f'{y}-01-01', min(f'{y}-12-31', through)) for y in sorted(missing)]
            if scope == 'recent':
                trades = calendar_dates(calendar, through)
                tail = trades[-10:]
                versions = {}
                for year in {int(day[:4]) for day in tail}:
                    versions.update(expand_versions(unit['price_ranges'].get(str(year), []), year))
                # A partial initialization can still have fully verified recent data.
                # Require every requested trading date and a fresh source version.
                now = datetime.now(CHINA)
                if any(datetime.fromisoformat(value) > now for value in versions.values()):
                    raise ValueError('远航近期覆盖版本超前')
                valid_years = {h['quote_year'] for h in heads if h['contract_version'] == CONTRACT}
                if all(int(day[:4]) in valid_years and day in versions
                       and datetime.fromisoformat(versions[day]).astimezone(CHINA).date().isoformat() >= through
                       for day in tail):
                    coverage = through
                else:
                    coverage = (date.fromisoformat(tail[0]) - timedelta(days=1)).isoformat()
            plan = plan_daily(code, through=through, calendar=calendar, coverage=min(coverage, through) if coverage else None,
                full_checked=full_checked, latest_quote=latest, native_market=heads[-1]['native_market'],
                gaps=gaps, force=force, scope=scope)
            if plan.mode == 'range':
                year = int(plan.start[:4])
                if contiguous_through(unit['price_ranges'].get(str(year), []), year) is None:
                    # Annual proof requires a January-1 prefix. A newly reached
                    # year is initialized once; this never authorizes whole-history reuse.
                    plan = replace(plan, start=f'{year}-01-01', reason='missing_annual_prefix')
        plans[code] = asdict(plan)
    return plans
