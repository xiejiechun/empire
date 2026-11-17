"""Read-only ETF estimate readiness; missing semantics never become a cash flow."""

from collections import Counter
from decimal import Decimal

from sqlalchemy import text

from empire.features.etf_fundamentals.contract import digest, number
from empire.features.yuanhang_etf.contract import CATALOG_PROJECT
from empire.plugins.infra.collection_state import read_state


def estimate(pool, current, previous, nav, *, adjustments=None):
    missing = Counter(
        missing_shares=0, missing_nav=0, income_only=0, unknown_currency=0, event_review=0
    )
    amount, covered, candidates = Decimal(0), 0, 0
    for code in pool:
        a, b, n = current.get(code), previous.get(code), nav.get(code)
        if a is None or b is None:
            missing["missing_shares"] += 1
            continue
        if n is None or n.get("value_kind") == "nav" and n.get("unit_nav") is None:
            missing["missing_nav"] += 1
            continue
        if n.get("value_kind") != "nav":
            missing["income_only"] += 1
            continue
        candidates += 1
        currency_ready = n.get("currency") == "CNY"
        event_ready = adjustments is not None and code in adjustments
        missing["unknown_currency"] += int(not currency_ready)
        missing["event_review"] += int(not event_ready)
        if currency_ready and event_ready:
            amount += (Decimal(a) - Decimal(b) - Decimal(adjustments[code])) * Decimal(
                n["unit_nav"]
            )
            covered += 1
    return dict(
        amount_yuan=number(amount) if covered else None,
        covered_count=covered,
        candidate_count=candidates,
        target_count=len(pool),
        missing=dict(missing),
    )


def read_etf_flows(conn, selected, previous, calendar, namespace):
    empty = dict(
        current=None,
        previous=None,
        basis="按当前ETF目录回看",
        catalog_hash=None,
        issue="ETF归档数据尚未准备",
    )
    if previous is None:
        return empty
    before = None
    for ordinal in range(previous.toordinal() - 1, min(calendar).toordinal() - 1, -1):
        from datetime import date

        d = date.fromordinal(ordinal)
        if d not in calendar:
            break
        if calendar[d]:
            before = d
            break
    if before is None:
        return {**empty, "issue": "前两交易日历不足"}
    catalog = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT unified_code AS code,name,native_market "
                "FROM yuanhang_etf WHERE active=TRUE ORDER BY unified_code LIMIT 5001"
            )
        ).mappings()
    ]
    state = read_state(conn, namespace, CATALOG_PROJECT, "ths_yuanhang")
    if (
        not catalog
        or len(catalog) > 5000
        or state.get("catalog_hash") != digest(catalog)
        or state.get("count") != len(catalog)
    ):
        return {**empty, "issue": "当前ETF目录集合证明不匹配"}
    dates = [selected.isoformat(), previous.isoformat(), before.isoformat()]
    args = dict(d0=dates[0], d1=dates[1], d2=dates[2])
    facts = (
        conn.execute(
            text(
                "SELECT unified_code,share_date,source,name,total_shares,source_group,source_type "
                "FROM etf_daily_share WHERE share_date IN (:d0,:d1,:d2) ORDER BY share_date,source,unified_code LIMIT 30001"
            ),
            args,
        )
        .mappings()
        .all()
    )
    if len(facts) > 30000:
        return {**empty, "issue": "ETF份额集合超过查询上限"}
    groups = {(s, d): [] for s in ("sse", "szse") for d in dates}
    for r in facts:
        group = (r["source"], r["share_date"].isoformat())
        if group not in groups:
            return {**empty, "issue": "ETF份额来源异常"}
        groups[group].append(
            [
                r["unified_code"],
                r["name"],
                number(r["total_shares"]),
                r["source_group"],
                r["source_type"],
            ]
        )
    heads = {
        (r["source"], r["share_date"].isoformat()): r
        for r in conn.execute(
            text(
                "SELECT * FROM etf_share_day "
                "WHERE share_date IN (:d0,:d1,:d2) ORDER BY source,share_date LIMIT 7"
            ),
            args,
        ).mappings()
    }
    shares, invalid = {d: {} for d in dates}, 0
    for group, rows in groups.items():
        h = heads.get(group)
        if h is None or (
            h["contract_version"],
            h["row_count"],
            h["key_hash"],
            h["content_hash"],
        ) != (1, len(rows), digest([r[0] for r in rows]), digest(rows)):
            invalid += 1
            continue
        shares[group[1]].update({r[0]: r[2] for r in rows})
    nav = {dates[0]: {}, dates[1]: {}}
    records = (
        conn.execute(
            text(
                "SELECT unified_code,nav_date,value_kind,unit_nav,currency FROM etf_daily_nav "
                "WHERE nav_date IN (:d0,:d1) ORDER BY nav_date,unified_code LIMIT 10001"
            ),
            args,
        )
        .mappings()
        .all()
    )
    if len(records) > 10000:
        return {**empty, "issue": "ETF净值集合超过查询上限"}
    for r in records:
        nav[r["nav_date"].isoformat()][r["unified_code"]] = r
    pool = [r["code"] for r in catalog]
    return dict(
        current=estimate(pool, shares[dates[0]], shares[dates[1]], nav[dates[0]]),
        previous=estimate(pool, shares[dates[1]], shares[dates[2]], nav[dates[1]]),
        basis=empty["basis"],
        catalog_hash=digest(catalog),
        issue=f"{invalid}个来源日期未具备完整份额证明" if invalid else "",
    )
