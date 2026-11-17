"""Plan from SQL business proofs, including cold-cache recovery and long outages."""

from datetime import date, datetime, timedelta

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.etf_fundamentals.contract import CONTRACT, START, coverage_through, day, digest
from empire.plugins.infra.collection_state import read_state
from empire.sources.yuanhang_ranges import validated_segments


def scope(conn, last=None):
    through, reason = read_trade_day_cutoff(conn, datetime.now(CHINA))
    if through is None:
        raise ValueError(reason or "ETF需要完整正式交易日历")
    cutoff = through.date().isoformat()
    if last and day(last) > cutoff:
        raise ValueError("ETF采集截止必须是已结束日期")
    last = last or cutoff
    records = conn.execute(
        text(
            "SELECT trade_date,is_trade FROM trade_calendar "
            "WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date LIMIT 10001"
        ),
        dict(first=START, last=last),
    ).all()
    from datetime import date, timedelta

    first = date.fromisoformat(START)
    count = (date.fromisoformat(last) - first).days + 1
    if len(records) != count or any(
        r[0] != first + timedelta(days=i) or r[1] not in (0, 1) for i, r in enumerate(records)
    ):
        raise ValueError("ETF正式交易日历缺日，须先补齐")
    trades = [r[0].isoformat() for r in records if r[1]]
    if not trades:
        raise ValueError("ETF声明日期范围没有已确认交易日")
    return last, trades


def share_plan(conn, namespace, source, *, start=None, end=None, sample_dates=None, fresh=False):
    last, trades = scope(conn, end)
    first = day(start or START)
    if first < START or first > last:
        raise ValueError("ETF份额起点无效")
    if sample_dates is not None:
        if (
            not isinstance(sample_dates, (list, tuple))
            or not 1 <= len(sample_dates) <= 1000
            or len(set(sample_dates)) != len(sample_dates)
        ):
            raise ValueError("ETF份额样本日期无效")
        selected = sorted(day(d) for d in sample_dates)
        if not set(selected) <= {d for d in trades if first <= d <= last}:
            raise ValueError("ETF份额样本必须为范围内正式交易日")
        return dict(units=[dict(date=d) for d in selected], recent=trades[-5:])
    heads = {
        r[0].isoformat()
        for r in conn.execute(
            text(
                "SELECT share_date FROM etf_share_day "
                "WHERE source=:source AND contract_version=:contract AND share_date BETWEEN :first AND :last "
                "ORDER BY share_date LIMIT 10001"
            ),
            dict(source=source, contract=CONTRACT, first=first, last=last),
        )
    }
    dates = [d for d in trades if first <= d <= last]
    recent = dates[-5:]
    missing = [d for d in dates if d not in heads and d not in recent][:20]
    state = read_state(conn, namespace, source + "-etf-shares", source)
    month = datetime.now(CHINA).strftime("%Y-%m")
    older = [d for d in dates if d in heads and d not in recent]
    # Stable round-robin monthly slice; a repeated run in the same month does not re-download it.
    offset = (int(month[:4]) * 12 + int(month[5:])) * 20 % max(1, len(older))
    candidates = (older + older)[offset : offset + min(20, len(older))]
    revision = [d for d in candidates if state.get("observed", {}).get(d, "")[:7] != month]
    if fresh:
        missing = [d for d in dates if d not in recent][:20]
    selected = list(dict.fromkeys([*recent, *missing, *revision]))
    return dict(units=[dict(date=d) for d in selected], recent=trades[-5:])


def nav_plan(conn, namespace, catalog, *, start=None, end=None, fresh=False):
    last, trades = scope(conn, end)
    first = day(start) if start else None
    if first and (first < START or first > last):
        raise ValueError("ETF净值起点无效")
    if first:
        return dict(
            units=[dict(code=r["code"], start=first, through=last) for r in catalog],
            recent=trades[-10:],
        )
    state = read_state(conn, namespace, "ttjj-etf-nav", "ttjj")
    units = state.get("units", {})
    heads = {}
    for r in conn.execute(
        text(
            "SELECT unified_code,nav_year,verified_through,contract_version "
            "FROM etf_nav_year ORDER BY unified_code,nav_year LIMIT 150001"
        )
    ).mappings():
        heads[(r["unified_code"], r["nav_year"])] = r
    if len(heads) >= 150000:
        raise ValueError("ETF年度证明超过声明范围")
    recent, history, revision_candidates = [], [], []
    last_year = int(last[:4])
    for row in catalog:
        code = row["code"]
        owned = units.get(code, {}).get("ranges", {})
        trusted = {}
        for y in range(int(START[:4]), last_year + 1):
            head = heads.get((code, y))
            through = coverage_through(owned.get(str(y), []), y)
            stored = (
                head["verified_through"].isoformat() if head and head["verified_through"] else None
            )
            if head and head["contract_version"] == CONTRACT and stored == through:
                trusted[y] = validated_segments(owned.get(str(y), []), y)
                if y < last_year and trusted[y]:
                    revision_candidates.append((code, y, owned[str(y)]))
        latest = max((end for segments in trusted.values() for _, end, _ in segments), default=None)
        window_start = trades[-min(10, len(trades))]
        begin = min(window_start, (latest + timedelta(days=1)).isoformat()) if latest else window_start
        recent.append(dict(code=code, start=begin, through=last))
        if not latest:
            history.append(dict(code=code, start=START, through=last))
            continue
        # Repair the first uncovered natural-date interval. Recent observations
        # are valid even when an earlier hole prevents a contiguous-year proof.
        for y in range(int(START[:4]), last_year + 1):
            needed = date.fromisoformat(max(START, f"{y}-01-01"))
            end = date.fromisoformat(min(last, f"{y}-12-31"))
            for first_segment, last_segment, _ in trusted.get(y, []):
                if first_segment > needed:
                    end = min(end, first_segment - timedelta(days=1))
                    break
                needed = max(needed, last_segment + timedelta(days=1))
            # The upcoming recent request already covers the suffix.
            end = min(end, date.fromisoformat(begin) - timedelta(days=1))
            if needed <= end:
                history.append(dict(code=code, start=needed.isoformat(), through=end.isoformat()))
                break
    if fresh:
        history = [dict(code=r["code"], start=START, through=last) for r in catalog]
    chosen = history[:32]
    month = datetime.now(CHINA).strftime("%Y-%m")
    if revision_candidates and not fresh:
        offset = (int(month[:4]) * 12 + int(month[5:])) * 32 % len(revision_candidates)
        for code, year, segments in (revision_candidates + revision_candidates)[
            offset : offset + min(32, len(revision_candidates))
        ]:
            if max(s[2] for s in segments)[:7] != month and not any(
                u["code"] == code and u["start"][:4] <= str(year) <= u["through"][:4]
                for u in chosen
            ):
                chosen.append(
                    dict(code=code, start=max(START, f"{year}-01-01"), through=f"{year}-12-31")
                )
    result = [
        u
        for u in recent
        if not any(
            h["code"] == u["code"] and h["start"] <= u["start"] and h["through"] >= u["through"]
            for h in chosen
        )
    ]
    result.extend(chosen)
    return dict(units=result, recent=trades[-10:], catalog_hash=digest(catalog))
