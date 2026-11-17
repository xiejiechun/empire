"""Content-bound SQL audits; storage completeness and use restrictions are separate."""

from datetime import date

from sqlalchemy import text

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.features.etf_fundamentals import nav_dataset, share_dataset
from empire.features.etf_fundamentals.contract import CONTRACT, coverage_through, day, digest
from empire.features.etf_fundamentals.planning import scope as source_scope
from empire.plugins.infra.collection_state import read_state
from empire.sources.yuanhang_ranges import versions_on


async def checks(query, source, request=None):
    scope = PreparationScope.parse(request)
    catalog = (
        await query.directory.catalog(list(scope.codes) if scope.codes else None)
        if source == "ttjj"
        else []
    )

    def audit(conn):
        last, trades = source_scope(conn, scope.end)
        window = 10 if source == "ttjj" else 5
        first = day(scope.start or trades[-min(window, len(trades))])
        state = read_state(
            conn,
            query.namespace,
            "ttjj-etf-nav" if source == "ttjj" else source + "-etf-shares",
            source,
        )
        count, valid, absent, empty = 0, True, 0, 0
        if source != "ttjj":
            heads = {
                r["share_date"].isoformat(): r
                for r in conn.execute(
                    text(
                        "SELECT * FROM etf_share_day "
                        "WHERE source=:source AND share_date BETWEEN :first AND :last ORDER BY share_date LIMIT 10001"
                    ),
                    dict(source=source, first=first, last=last),
                ).mappings()
            }
            expected = [d for d in trades if first <= d <= last]
            for d in expected:
                h = heads.get(d)
                if h is None:
                    valid, absent = False, absent + 1
                    continue
                rows = share_dataset.read_rows(conn, source, d)
                count += len(rows)
                valid &= (
                    h["key_hash"],
                    h["content_hash"],
                    h["row_count"],
                    h["contract_version"],
                ) == (digest([r[0] for r in rows]), digest(rows), len(rows), CONTRACT)
                empty += int(not rows)
            return valid and bool(expected), count, absent, empty
        if not catalog or len(catalog) * (int(last[:4]) - int(first[:4]) + 1) > 150000:
            raise ValueError("ETF净值数据准备范围为空或超界")
        codes = [item["code"] for item in catalog]
        heads = {
            (r["unified_code"], r["nav_year"]): r
            for r in conn.execute(
                text(
                    "SELECT * FROM etf_nav_year WHERE nav_year BETWEEN :first AND :last "
                    "ORDER BY unified_code,nav_year LIMIT 150001"
                ),
                dict(first=int(first[:4]), last=int(last[:4])),
            ).mappings()
        }
        if len(heads) > 150000:
            raise ValueError("ETF净值覆盖证明超界")
        for year in range(int(first[:4]), int(last[:4]) + 1):
            a = date.fromisoformat(max(first, f"{year}-01-01"))
            b = date.fromisoformat(min(last, f"{year}-12-31"))
            required = [
                date.fromordinal(i).isoformat() for i in range(a.toordinal(), b.toordinal() + 1)
            ]
            for offset in range(0, len(codes), 64):
                groups = nav_dataset.read_groups(conn, codes[offset : offset + 64], year)
                for code, rows in groups.items():
                    head = heads.get((code, year))
                    if head is None:
                        valid, absent = False, absent + 1
                        continue
                    ranges = state.get("units", {}).get(code, {}).get("ranges", {})
                    segments = ranges.get(str(year), [])
                    valid &= (
                        head["key_hash"],
                        head["content_hash"],
                        head["row_count"],
                        head["contract_version"],
                    ) == (digest([r[0] for r in rows]), digest(rows), len(rows), CONTRACT)
                    complete = set(versions_on(segments, year, required)) == set(required)
                    valid &= complete
                    absent += int(not complete)
                    empty += int(complete and not any(first <= r[0] <= last for r in rows))
                    valid &= (
                        head["verified_through"].isoformat() if head["verified_through"] else None
                    ) == coverage_through(segments, year)
                    count += sum(first <= r[0] <= last for r in rows)
        return valid, count, absent, empty

    valid, count, absent, empty = await query.read(audit)
    return tuple(
        CheckEvidence(k, "pass" if valid else "fail", msg)
        for k, msg in (
            (
                "coverage",
                f"范围内{count}条来源事实，缺少覆盖单元{absent}，已核验源端空单元{empty}；源端空不等于没有ETF",
            ),
            ("keys", "逐完整来源日/证券年度核对业务键集合与正文摘要"),
            ("fields", "精确份额、净值/收益分列；申赎状态、分红说明忠实保留"),
            ("quality", "源端空字段保留；估算另需币种和非申赎份额变动依据"),
            ("freshness", "仅证明查询范围已核验；源端公布延迟不填零"),
        )
    ) + (
        CheckEvidence(
            "temporal",
            "fail",
            "缺少完整历史公布时刻和旧版本，不能用于严格时点回放",
            blocking=scope.purpose != "analysis",
            reason="source_limit",
        ),
    )
