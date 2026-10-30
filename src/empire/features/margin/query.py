"""Bounded SQL browsing; derived values use the prior source row across page boundaries."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.margin.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    PROJECT,
    TABLES,
    day,
    digest,
    security,
    validate,
)
from empire.features.margin.dataset import read_rows
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page


class MarginDataPlugin:
    manifest = PluginManifest(
        "data.margin",
        "个股融资融券查询",
        requires=("mysql.store",),
        provides=("margin.query",),
        description="按日期和证券查询结构化来源事实",
    )

    def __init__(self, namespace="empire"):
        self.namespace, self.mysql = namespace, None
        self.preparation = tuple(
            PreparationContribution(
                req,
                "margin.query",
                "通达信",
                PROJECT,
                JOB,
                DATASET,
                "collector.tdx_margin",
                ("tests/test_tdx_margin.py",),
                ("tests/integration/test_margin_archive.py",),
                method="check_" + req,
                scoped=True,
                response_group=DATASET,
            )
            for req in ("financing", "short_lending")
        )
        for req in ("financing", "short_lending"):
            setattr(self, "check_" + req, partial(self.preparation_check, req))

    async def start(self, context):
        from empire.plugins.infra.schema_manifest import manifest

        self.mysql = context.get("mysql.store")
        for table in TABLES:
            await self.mysql.require_schema(
                *schema_contract(table, *manifest()["tables"][table]["columns"])
            )
        return {"margin.query": self}

    async def securities(self, codes=None):
        if codes is not None:
            if (
                not isinstance(codes, (list, tuple))
                or not 1 <= len(codes) <= 30000
                or len(set(codes)) != len(codes)
            ):
                raise ValueError("融资融券指定证券池无效")
            return sorted(security(c) for c in codes)

        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT unified_code FROM stock UNION SELECT unified_code "
                            "FROM margin_security ORDER BY unified_code LIMIT 30001"
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows or len(rows) > 30000:
                    raise ValueError("融资融券证券池为空或超限")
                return [security(c) for c in rows]

        return await self.mysql.read(read)

    async def browse(self, code="", start="", end="", after=None, limit=200, order=None):
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"(?:\d{0,6}|\d{6}\.(SH|SZ|BJ))", code)
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValueError("融资融券查询条件无效")
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, args = ["TRUE"], dict(limit=limit + 1)
        if code:
            clauses.append("d.unified_code LIKE :code")
            args["code"] = code if "." in code else code + "%"
        for key, value, op in (("start", scope.start, ">="), ("end", scope.end, "<=")):
            if value:
                clauses.append("d.trade_date" + op + ":" + key)
                args[key] = value
        if after is not None and order is None:
            if not isinstance(after, (list, tuple)) or len(after) != 2:
                raise ValueError("融资融券查询游标无效")
            day(after[0])
            security(after[1])
            clauses.append("(d.trade_date,d.unified_code)<(:last_day,:last_code)")
            args.update(last_day=after[0], last_code=after[1])

        def read():
            with self.mysql.read_engine.connect() as conn:
                if order is not None:
                    from empire.features.margin.ordering import sort_fields

                    relation = (
                        'SELECT d.*,p.financing_balance AS previous_financing,'
                        'p.lending_balance AS previous_lending FROM margin_daily d '
                        'LEFT JOIN margin_daily p ON p.unified_code=d.unified_code '
                        'AND p.trade_date=(SELECT MAX(q.trade_date) FROM margin_daily q '
                        'WHERE q.unified_code=d.unified_code AND q.trade_date<d.trade_date) WHERE '
                        + ' AND '.join(clauses)
                    )
                    values, cursor = ordered_page(
                        conn, relation, {k: v for k, v in args.items() if k != 'limit'},
                        order=order, fields={**column_fields(('unified_code', 'trade_date', *FIELDS)),
                                             **sort_fields()},
                        identity=('unified_code', 'trade_date'), after=after, limit=limit,
                    )
                    for row in values:
                        row['trade_date'] = row['trade_date'].isoformat()
                        row.update(derived(row))
                    return dict(rows=values, next=cursor)
                # Limit first; indexed predecessor lookup stays bounded to this page.
                sql = "SELECT d.*,p.financing_balance AS previous_financing,p.lending_balance AS previous_lending "
                sql += "FROM (SELECT d.* FROM margin_daily d WHERE " + " AND ".join(clauses)
                sql += " ORDER BY d.trade_date DESC,d.unified_code DESC LIMIT :limit) d "
                sql += "LEFT JOIN margin_daily p ON p.unified_code=d.unified_code AND p.trade_date="
                sql += (
                    "(SELECT q.trade_date FROM margin_daily q WHERE q.unified_code=d.unified_code "
                )
                sql += "AND q.trade_date<d.trade_date ORDER BY q.trade_date DESC LIMIT 1) "
                sql += "ORDER BY d.trade_date DESC,d.unified_code DESC"
                values = [dict(r) for r in conn.execute(text(sql), args).mappings()]
                for row in values:
                    row["trade_date"] = row["trade_date"].isoformat()
                    row.update(derived(row))
                rows = values[:limit]
                return dict(
                    rows=rows,
                    next=[rows[-1]["trade_date"], rows[-1]["unified_code"]]
                    if len(values) > limit
                    else None,
                )

        return await self.mysql.read(read)

    async def history(self, code):
        security(code)

        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_rows(conn, code)

        return await self.mysql.read(read)

    async def preparation_check(self, requirement, request=None):
        scope = PreparationScope.parse(request)

        def audit():
            now = datetime.now(UTC)
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, PROJECT, "tdx")
                heads = (
                    conn.execute(
                        text("SELECT * FROM margin_security ORDER BY unified_code LIMIT 30001")
                    )
                    .mappings()
                    .all()
                )
                heads = [
                    h
                    for h in heads
                    if not scope.codes
                    or h["unified_code"][:6] in scope.codes
                    or h["unified_code"] in scope.codes
                ]
                valid = bool(heads) and len(heads) <= 30000
                if scope.codes:
                    valid &= all(
                        any(h["unified_code"] == c or h["unified_code"][:6] == c for h in heads)
                        for c in scope.codes
                    )
                else:
                    pool = (
                        conn.execute(text("SELECT unified_code FROM stock LIMIT 30001"))
                        .scalars()
                        .all()
                    )
                    valid &= (
                        bool(pool)
                        and len(pool) <= 30000
                        and set(pool) <= {h["unified_code"] for h in heads}
                    )
                fresh, count = valid, 0
                for h in heads:
                    rows = read_rows(conn, h["unified_code"])
                    try:
                        validate(rows, now.date().isoformat())
                        valid &= (
                            h["contract_version"] == CONTRACT
                            and h["row_count"] == len(rows)
                            and h["content_hash"] == digest(rows)
                        )
                        valid &= h["first_date"] == (
                            datetime.fromisoformat(rows[-1][0]).date() if rows else None
                        )
                        valid &= h["last_date"] == (
                            datetime.fromisoformat(rows[0][0]).date() if rows else None
                        )
                        stamp = datetime.fromisoformat(state.get("observed", {})[h["unified_code"]])
                        fresh &= timedelta(0) <= now - stamp <= timedelta(days=3)
                    except (ValueError, KeyError, TypeError):
                        valid = fresh = False
                    count += sum(scope.includes(r[0]) for r in rows)
                return valid, fresh, count, len(heads)

        valid, fresh, count, securities = await self.mysql.read(audit)
        return tuple(
            CheckEvidence(key, "pass" if ok else "fail", message)
            for key, ok, message in (
                ("fields", valid, f"{requirement}来源必需数值、单位与日期核验；范围内{count}条"),
                ("keys", valid, "证券/日期唯一，SQL集合摘要与完整来源证明一致"),
                (
                    "coverage",
                    valid,
                    f"核验{securities}只证券的来源完整响应；未返回日期不推断为零或具备资格",
                ),
                ("quality", valid, "保留来源数值；派生偿还与比例按页面公式，最早记录边界单独标识"),
                (
                    "freshness",
                    valid and fresh,
                    "SQL完整核验时间3天内；来源最新交易日不保证等于今天",
                ),
            )
        ) + (
            CheckEvidence(
                "temporal",
                "fail",
                "来源无公布时间；不能直接用于严格历史信号回放",
                blocking=scope.purpose != "analysis",
            ),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}


def derived(row):
    previous = row["previous_financing"]
    lending = row["previous_lending"]
    amount = row["lending_balance"] * row["close_price"] if row["close_price"] is not None else None
    return dict(
        financing_repaid=(previous or Decimal(0)) + row["financing_buy"] - row["financing_balance"],
        lending_repaid=(lending or Decimal(0)) + row["lending_sell"] - row["lending_balance"],
        first_source_row=previous is None,
        lending_amount=amount,
        margin_difference=row["financing_balance"] - amount if amount is not None else None,
        financing_buy_pct=row["financing_buy"] / row["market_turnover"] * 100
        if row["market_turnover"]
        else None,
        lending_sell_pct=row["lending_sell"] / row["market_volume"] * 100
        if row["market_volume"]
        else None,
    )
