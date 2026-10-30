"""SQL-only bounded date/industry browsing and complete-day content audits."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.core.time import CHINA
from empire.features.industry_margin.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    PROJECT,
    START,
    TABLES,
    dates,
    day,
    digest,
    validate,
)
from empire.features.industry_margin.dataset import read_days, read_rows
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.query_order import column_fields, ordered_page


class IndustryMarginDataPlugin:
    manifest = PluginManifest(
        "data.industry_margin",
        "行业融资融券查询",
        requires=("mysql.store",),
        provides=("industry_margin.query",),
        description="按日期和来源行业名称浏览",
    )

    def __init__(self, namespace="empire"):
        self.namespace, self.mysql = namespace, None
        self.preparation = (
            PreparationContribution(
                "industry_margin",
                "industry_margin.query",
                "通达信",
                PROJECT,
                JOB,
                DATASET,
                "collector.tdx_industry_margin",
                ("tests/test_industry_margin.py",),
                ("tests/integration/test_industry_margin_archive.py",),
                scoped=True,
            ),
        )

    async def start(self, context):
        from empire.plugins.infra.schema_manifest import manifest

        self.mysql = context.get("mysql.store")
        for table in TABLES:
            await self.mysql.require_schema(
                *schema_contract(table, *manifest()["tables"][table]["columns"])
            )
        return {"industry_margin.query": self}

    async def covered(self, start, end):
        day(start), day(end)

        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT trade_date FROM industry_margin_day "
                            "WHERE trade_date BETWEEN :start AND :end AND contract_version=:contract "
                            "ORDER BY trade_date LIMIT 70001"
                        ),
                        dict(start=start, end=end, contract=CONTRACT),
                    )
                    .scalars()
                    .all()
                )
                if len(rows) > 70000:
                    raise ValueError("行业融资融券覆盖范围超限")
                return {d.isoformat() for d in rows}

        return await self.mysql.read(read)

    async def history(self, stamp):
        day(stamp)

        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_rows(conn, stamp)

        return await self.mysql.read(read)

    async def browse(self, search="", start="", end="", after=None, limit=200, order=None):
        if (
            not isinstance(search, str)
            or len(search) > 64
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValueError("行业融资融券查询条件无效")
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, args = ["TRUE"], dict(limit=limit + 1)
        if search:
            clauses.append("industry_name=:name")
            args["name"] = search
        for key, value, op in (("start", scope.start, ">="), ("end", scope.end, "<=")):
            if value:
                day(value)
                clauses.append("trade_date" + op + ":" + key)
                args[key] = value
        if after is not None and order is None:
            if (
                not isinstance(after, (list, tuple))
                or len(after) != 2
                or not isinstance(after[1], str)
                or len(after[1]) > 64
            ):
                raise ValueError("行业融资融券游标无效")
            day(after[0])
            clauses.append("(trade_date,industry_name)<(:last_day,:last_name)")
            args.update(last_day=after[0], last_name=after[1])

        def read():
            with self.mysql.read_engine.connect() as conn:
                if order is not None:
                    fields = column_fields(('trade_date', 'industry_name', *FIELDS))
                    fields['margin_difference'] = 'q.financing_balance - q.lending_balance / 10000'
                    records, cursor = ordered_page(
                        conn, 'SELECT * FROM industry_margin_daily WHERE ' + ' AND '.join(clauses),
                        {k: v for k, v in args.items() if k != 'limit'}, order=order,
                        fields=fields, identity=('trade_date', 'industry_name'), after=after, limit=limit,
                    )
                    for row in records:
                        row['trade_date'] = row['trade_date'].isoformat()
                        row['margin_difference'] = (
                            row['financing_balance'] - row['lending_balance'] / Decimal(10000)
                            if row['financing_balance'] is not None and row['lending_balance'] is not None
                            else None
                        )
                    return dict(rows=records, next=cursor)
                rows = (
                    conn.execute(
                        text(
                            "SELECT * FROM industry_margin_daily WHERE "
                            + " AND ".join(clauses)
                            + " ORDER BY trade_date DESC,industry_name DESC LIMIT :limit"
                        ),
                        args,
                    )
                    .mappings()
                    .all()
                )
                result = []
                for item in rows[:limit]:
                    row = dict(item)
                    row["trade_date"] = row["trade_date"].isoformat()
                    financing, lending = row["financing_balance"], row["lending_balance"]
                    row["margin_difference"] = (
                        financing - lending / Decimal(10000)
                        if financing is not None and lending is not None
                        else None
                    )
                    result.append(row)
                return dict(
                    rows=result,
                    next=[result[-1]["trade_date"], result[-1]["industry_name"]]
                    if len(rows) > limit
                    else None,
                )

        return await self.mysql.read(read)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        first = day(scope.start or START)

        def audit():
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, PROJECT, "tdx")
                last = day(
                    scope.end
                    or state.get("source_latest")
                    or datetime.now(CHINA).date().isoformat()
                )
                expected = set(dates(first, last))
                heads = (
                    conn.execute(
                        text(
                            "SELECT * FROM industry_margin_day WHERE trade_date BETWEEN :first AND :last "
                            "ORDER BY trade_date LIMIT 70001"
                        ),
                        dict(first=first, last=last),
                    )
                    .mappings()
                    .all()
                )
                keys = {h["trade_date"].isoformat() for h in heads}
                valid, fields, count, negative = keys == expected, True, 0, 0
                for offset in range(0, len(heads), 31):
                    batch = heads[offset : offset + 31]
                    contents = read_days(conn, [h["trade_date"].isoformat() for h in batch])
                    for head in batch:
                        rows = contents[head["trade_date"].isoformat()]
                        try:
                            validate(rows)
                            valid &= (
                                head["content_hash"] == digest(rows)
                                and head["row_count"] == len(rows)
                                and head["contract_version"] == CONTRACT
                            )
                        except (ValueError, TypeError):
                            valid = False
                        fields &= all(v is not None for row in rows for v in row[1:])
                        negative += sum(
                            v is not None and Decimal(v) < 0 for row in rows for v in row[1:]
                        )
                        count += len(rows)
                return valid, fields, count, len(expected - keys), negative

        valid, fields, count, missing, negative = await self.mysql.read(audit)
        return (
            CheckEvidence(
                "coverage",
                "pass" if valid else "fail",
                f"自然日完整来源集合；缺少{missing}日，{count}行",
            ),
            CheckEvidence(
                "keys", "pass" if valid else "fail", "日期×来源行业名称集合及正文摘要核对"
            ),
            CheckEvidence(
                "fields",
                "pass" if fields and valid else "fail",
                "融资亿元、融券万元/万股；未知值不填零",
            ),
            CheckEvidence(
                "quality",
                "pass" if fields and valid and not negative else "fail",
                f"有限数值与8位精度；来源负值{negative}项，保留原值但不可直接用于常规分析；有效空日不推断休市",
            ),
            CheckEvidence(
                "freshness",
                "pass" if valid else "fail",
                "仅确认声明日期范围已归档；不以观测时间掩盖缺日",
            ),
            CheckEvidence(
                "temporal",
                "fail",
                "无公布时间或历史分类版本，不支持严格历史信号回放",
                blocking=scope.purpose != "analysis",
            ),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
