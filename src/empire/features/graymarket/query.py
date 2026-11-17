"""Typed SQL browsing and actual complete-calendar/day audits."""

from datetime import date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.features.graymarket.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    PROJECT,
    START,
    TABLES,
    day,
    digest,
)
from empire.features.graymarket.dataset import read_rows
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page


def calendar_dates(conn, first, last):
    a, b = date.fromisoformat(day(first)), date.fromisoformat(day(last))
    count = (b - a).days + 1
    if not 1 <= count <= 60000:
        raise ValueError("资金榜日期范围无效或超界")
    rows = conn.execute(
        text(
            "SELECT trade_date,is_trade FROM trade_calendar "
            "WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date LIMIT 60001"
        ),
        dict(first=first, last=last),
    ).all()
    if len(rows) != count or any(
        r[0] != a + timedelta(days=i) or r[1] not in (0, 1) for i, r in enumerate(rows)
    ):
        raise ValueError("正式交易日历存在缺日，先补齐日历再采资金榜")
    return [r[0].isoformat() for r in rows if r[1]]


class GraymarketDataPlugin:
    manifest = PluginManifest(
        "data.graymarket",
        "明盘暗盘资金榜查询",
        requires=("mysql.store",),
        provides=("graymarket.query",),
        description="完整日榜与证券日期范围查询",
    )

    def __init__(self, namespace="empire"):
        self.namespace, self.mysql = namespace, None
        self.preparation = (
            PreparationContribution(
                "graymarket",
                "graymarket.query",
                "东方财富",
                PROJECT,
                JOB,
                DATASET,
                "collector.eastmoney_graymarket",
                ("tests/test_graymarket.py", "tests/test_graymarket_lifecycle.py"),
                ("tests/integration/test_graymarket_archive.py",),
                scoped=True,
            ),
        )

    async def start(self, context):
        self.context = context
        from empire.plugins.infra.schema_manifest import manifest

        self.mysql = context.get("mysql.store")
        for table in TABLES:
            await self.mysql.require_schema(
                *schema_contract(table, *manifest()["tables"][table]["columns"])
            )
        return {"graymarket.query": self}

    async def trading_dates(self, first, last):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return calendar_dates(conn, first, last)

        return await self.mysql.read(read)

    async def covered(self, first, last):
        day(first), day(last)

        def read():
            with self.mysql.read_engine.connect() as conn:
                return {
                    r[0].isoformat()
                    for r in conn.execute(
                        text(
                            "SELECT trade_date FROM graymarket_day WHERE trade_date BETWEEN :first AND :last "
                            "AND contract_version=:contract ORDER BY trade_date LIMIT 60001"
                        ),
                        dict(first=first, last=last, contract=CONTRACT),
                    )
                }

        return await self.mysql.read(read)

    async def maintenance_plan(self, last, *, recent=0):
        """Validate the calendar in SQL; return only three recent or five missing days."""
        count = (date.fromisoformat(day(last)) - date.fromisoformat(START)).days + 1
        if not 1 <= count <= 60000 or recent not in (0, 1, 3):
            raise ValueError("资金榜维护范围无效")

        def read():
            with self.mysql.read_engine.connect() as conn:
                args = dict(first=START, last=last, contract=CONTRACT)
                actual, valid = conn.execute(text(
                    "SELECT COUNT(*),COALESCE(SUM(is_trade IN (0,1)),0) FROM trade_calendar "
                    "WHERE trade_date BETWEEN :first AND :last"), args).one()
                if actual != count or valid != count:
                    raise ValueError("正式交易日历存在缺日，先补齐日历再采资金榜")
                sql = ("SELECT c.trade_date FROM trade_calendar c WHERE c.is_trade=1 "
                       "AND c.trade_date BETWEEN :first AND :last ")
                if recent:
                    sql += "ORDER BY c.trade_date DESC LIMIT :limit"
                else:
                    sql += ("AND NOT EXISTS (SELECT 1 FROM graymarket_day d WHERE d.trade_date=c.trade_date "
                            "AND d.contract_version=:contract) ORDER BY c.trade_date LIMIT :limit")
                values = conn.execute(text(sql), dict(args, limit=recent or 5)).scalars()
                return sorted(v.isoformat() for v in values)

        return await self.mysql.read(read)

    async def history(self, stamp):
        day(stamp)

        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_rows(conn, stamp)

        return await self.mysql.read(read)

    async def browse(self, code="", start="", end="", after=None, limit=200, order=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("资金榜分页上限200")
        scope = PreparationScope.parse(dict(start=start, end=end))
        terms, args = ["TRUE"], {}
        if code:
            from empire.features.graymarket.intraday_query import code_filter

            terms.append("unified_code LIKE :code")
            args["code"] = code_filter(code) + "%"
        for key, value, op in (("start", scope.start, ">="), ("end", scope.end, "<=")):
            if value:
                terms.append("trade_date" + op + ":" + key)
                args[key] = day(value)

        def read():
            with self.mysql.read_engine.connect() as conn:
                if order is not None:
                    rows, cursor = ordered_page(
                        conn,
                        "SELECT * FROM graymarket_daily WHERE " + " AND ".join(terms),
                        args,
                        order=order,
                        fields=column_fields(("trade_date", "unified_code", *FIELDS)),
                        identity=("trade_date", "unified_code"),
                        after=after,
                        limit=limit,
                    )
                else:
                    clauses, values = list(terms), {**args, "limit": limit + 1}
                    if after is not None:
                        if not isinstance(after, (list, tuple)) or len(after) != 2:
                            raise ValueError("资金榜游标无效")
                        day(after[0]), split_unified_code(after[1])
                        clauses.append("(trade_date,unified_code)<(:last_day,:last_code)")
                        values.update(last_day=after[0], last_code=after[1])
                    records = [
                        dict(r)
                        for r in conn.execute(
                            text(
                                "SELECT * FROM graymarket_daily WHERE "
                                + " AND ".join(clauses)
                                + " ORDER BY trade_date DESC,unified_code DESC LIMIT :limit"
                            ),
                            values,
                        ).mappings()
                    ]
                    rows = records[:limit]
                    cursor = (
                        [rows[-1]["trade_date"].isoformat(), rows[-1]["unified_code"]]
                        if len(records) > limit
                        else None
                    )
                for row in rows:
                    row["trade_date"] = row["trade_date"].isoformat()
                return dict(rows=rows, next=cursor)

        return await self.mysql.read(read)

    async def browse_live(self, filters, after=None, order=None, code=""):
        from empire.features.graymarket.intraday_query import browse_live

        return await browse_live(self.context, filters, after, order, code)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        first = day(scope.start or START)

        def audit():
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, PROJECT, "eastmoney")
                last = day(
                    scope.end
                    or state.get("source_latest")
                    or datetime.now(CHINA).date().isoformat()
                )
                expected = set(calendar_dates(conn, first, last))
                heads = list(
                    conn.execute(
                        text(
                            "SELECT * FROM graymarket_day WHERE "
                            "trade_date BETWEEN :first AND :last ORDER BY trade_date LIMIT 60001"
                        ),
                        dict(first=first, last=last),
                    ).mappings()
                )
                keys = {h["trade_date"].isoformat() for h in heads}
                valid, count = keys == expected and bool(expected), 0
                for head in heads:
                    rows = read_rows(conn, head["trade_date"].isoformat())
                    valid &= (
                        head["content_hash"],
                        head["row_count"],
                        head["contract_version"],
                    ) == (digest(rows), len(rows), CONTRACT)
                    count += len(rows)
                return valid, count, len(expected - keys)

        valid, count, missing = await self.mysql.read(audit)
        return tuple(
            CheckEvidence(k, "pass" if valid else "fail", message)
            for k, message in (
                ("coverage", f"交易日完整榜单核对，缺{missing}日，共{count}行"),
                ("keys", "证券/日期身份及完整日内容摘要"),
                ("fields", "金额元、比例小数、价格元；精确数值及必需字段"),
                ("quality", "来源模型估算；三项资金合计校验，不代表实际暗盘成交"),
                ("freshness", "仅确认请求范围覆盖；旧日期修订需显式重核"),
            )
        ) + (
            CheckEvidence(
                "temporal",
                "fail",
                "没有历史公布时刻或完整修订版本，不能用于严格历史信号回放",
                blocking=scope.purpose != "analysis",
            ),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
