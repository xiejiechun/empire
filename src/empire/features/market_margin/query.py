"""Bounded SQL market browsing and complete-source content checks."""

from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.market_margin.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    MARKETS,
    PROJECT,
    TABLES,
    digest,
    market,
    validate,
)
from empire.features.market_margin.dataset import read_rows
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page


class MarketMarginDataPlugin:
    manifest = PluginManifest(
        "data.market_margin",
        "市场融资融券查询",
        requires=("mysql.store",),
        provides=("market_margin.query",),
        description="同花顺四市场完整历史与结构化查询",
    )

    def __init__(self, namespace="empire"):
        self.namespace, self.mysql = namespace, None
        self.preparation = tuple(
            PreparationContribution(
                req,
                "market_margin.query",
                "同花顺",
                PROJECT,
                JOB,
                DATASET,
                "collector.ths_market_margin",
                ("tests/test_market_margin.py",),
                ("tests/integration/test_market_margin_archive.py",),
                method="check_" + req,
                scoped=True,
                response_group=DATASET,
            )
            for req in ("market_financing", "market_short_lending")
        )
        for req in ("market_financing", "market_short_lending"):
            setattr(self, "check_" + req, partial(self.preparation_check, req))

    async def start(self, context):
        from empire.plugins.infra.schema_manifest import manifest

        self.mysql = context.get("mysql.store")
        for table in TABLES:
            await self.mysql.require_schema(
                *schema_contract(table, *manifest()["tables"][table]["columns"])
            )
        return {"market_margin.query": self}

    async def markets(self, codes=None):
        if codes is None:
            return list(MARKETS)
        if (
            not isinstance(codes, (list, tuple))
            or not codes
            or len(codes) > 4
            or len(set(codes)) != len(codes)
        ):
            raise ValueError("市场范围无效")
        return [market(c) for c in codes]

    async def history(self, code):
        market(code)

        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_rows(conn, code)

        return await self.mysql.read(read)

    async def browse(self, search="", start="", end="", after=None, limit=200, order=None):
        if type(limit) is not int or not 1 <= limit <= 200 or not isinstance(search, str):
            raise ValueError("市场查询参数无效")
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, args = ["TRUE"], {}
        if search:
            code = next((k for k, v in MARKETS.items() if search in (k, v)), None)
            if code is None:
                raise ValueError("市场请选择99/3/2/4或完整市场名称")
            clauses.append("market_code=:code")
            args["code"] = code
        for key, value, op in (("start", scope.start, ">="), ("end", scope.end, "<=")):
            if value:
                clauses.append("trade_date" + op + ":" + key)
                args[key] = value

        def read():
            with self.mysql.read_engine.connect() as conn:
                if order is None:
                    params = {**args, "limit": limit + 1}
                    terms = list(clauses)
                    if after is not None:
                        if not isinstance(after, (list, tuple)) or len(after) != 2:
                            raise ValueError("市场查询游标无效")
                        from empire.features.market_margin.contract import day

                        day(after[0])
                        market(after[1])
                        terms.append("(trade_date,market_code)<(:last_day,:last_code)")
                        params.update(last_day=after[0], last_code=after[1])
                    values = [
                        dict(r)
                        for r in conn.execute(
                            text(
                                "SELECT * FROM market_margin_daily WHERE "
                                + " AND ".join(terms)
                                + " ORDER BY trade_date DESC,market_code DESC LIMIT :limit"
                            ),
                            params,
                        ).mappings()
                    ]
                    rows = values[:limit]
                    cursor = (
                        [rows[-1]["trade_date"].isoformat(), rows[-1]["market_code"]]
                        if len(values) > limit
                        else None
                    )
                else:
                    fields = column_fields(("market_code", "trade_date", *FIELDS))
                    fields["total_balance"] = (
                        "COALESCE(q.source_total,q.financing_balance+q.lending_balance)"
                    )
                    fields["market_name"] = (
                        "CASE q.market_code WHEN '99' THEN '沪深京合计' WHEN '3' THEN '沪市' WHEN '2' THEN '深市' ELSE '京市' END"
                    )
                    rows, cursor = ordered_page(
                        conn,
                        "SELECT * FROM market_margin_daily WHERE " + " AND ".join(clauses),
                        args,
                        order=order,
                        fields=fields,
                        identity=("market_code", "trade_date"),
                        after=after,
                        limit=limit,
                    )
                for row in rows:
                    row["trade_date"] = row["trade_date"].isoformat()
                    row["market_name"] = MARKETS[row["market_code"]]
                    row["total_balance"] = (
                        row["source_total"]
                        if row["source_total"] is not None
                        else row["financing_balance"] + row["lending_balance"]
                    )
                return dict(rows=rows, next=cursor)

        return await self.mysql.read(read)

    async def preparation_check(self, requirement, request=None):
        scope = PreparationScope.parse(request)

        def audit():
            now = datetime.now(UTC)
            with self.mysql.read_engine.connect() as conn:
                state = read_state(conn, self.namespace, PROJECT, "ths")
                heads = {
                    r["market_code"]: r
                    for r in conn.execute(text("SELECT * FROM market_margin_series")).mappings()
                }
                valid, fresh, count = set(heads) == set(MARKETS), True, 0
                for code in MARKETS:
                    rows, h = read_rows(conn, code), heads.get(code)
                    try:
                        validate(rows, now.date().isoformat(), code)
                        valid &= bool(h) and (
                            h["content_hash"],
                            h["row_count"],
                            h["contract_version"],
                        ) == (digest(rows), len(rows), CONTRACT)
                        valid &= (
                            bool(h)
                            and h["first_date"].isoformat() == rows[0][0]
                            and h["last_date"].isoformat() == rows[-1][0]
                        )
                        stamp = datetime.fromisoformat(state.get("observed", {})[code])
                        fresh &= timedelta(0) <= now - stamp <= timedelta(days=3)
                    except (ValueError, KeyError, TypeError, IndexError):
                        valid = fresh = False
                    count += sum(scope.includes(r[0]) for r in rows)
                return valid, fresh, count

        valid, fresh, count = await self.mysql.read(audit)
        return tuple(
            CheckEvidence(k, "pass" if ok else "fail", msg)
            for k, ok, msg in (
                (
                    "fields",
                    valid,
                    f"{requirement}金额元、股数、比例小数及缺值契约；范围内{count}行",
                ),
                ("keys", valid, "市场/日期唯一，实际SQL日期集合和数值与来源摘要一致"),
                ("coverage", valid, "四个完整来源序列核验；北交所2023-02-13起，不将未返回日填零"),
                ("quality", valid, "保留原始数值和NULL；合计为独立来源口径，不与分市场重复加总"),
                ("freshness", valid and fresh, "SQL核验观测3天内；实际最新日以来源为准"),
            )
        ) + (
            CheckEvidence(
                "temporal",
                "fail",
                "没有历史公布时刻/修订版本，严格信号回放受限",
                blocking=scope.purpose != "analysis",
            ),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
