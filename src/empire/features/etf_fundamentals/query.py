"""Formal bounded SQL browsing; collection never runs as a side effect of queries."""

from datetime import date

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.features.etf_fundamentals.contract import NAV_FIELDS, TABLES, day
from empire.features.etf_fundamentals.planning import nav_plan, share_plan
from empire.plugins.infra.query_order import column_fields, ordered_page


class Query:
    manifest = PluginManifest(
        "data.etf_fundamentals",
        "ETF份额与净值查询",
        requires=("mysql.store", "yuanhang.etfs.query"),
        provides=("etf.fundamentals.query",),
    )

    def __init__(self, namespace="empire"):
        self.namespace, self.mysql = namespace, None
        self.preparation = tuple(
            PreparationContribution(
                "etf_" + source + ("_nav" if source == "ttjj" else "_shares"),
                "etf.fundamentals.query",
                source,
                project,
                project + "-v1",
                "etf.nav.range" if source == "ttjj" else "etf.share.day",
                "collector." + project.replace("-", "_"),
                ("tests/test_etf_fundamentals.py", "tests/test_etf_fundamentals_lifecycle.py"),
                ("tests/integration/test_etf_fundamentals_archive.py",),
                method="check_" + source,
                scoped=True,
            )
            for source, project in (
                ("sse", "sse-etf-shares"),
                ("szse", "szse-etf-shares"),
                ("ttjj", "ttjj-etf-nav"),
            )
        )

    async def start(self, context):
        from empire.plugins.infra.schema_manifest import schema_contract

        self.mysql, self.directory = context.get("mysql.store"), context.get("yuanhang.etfs.query")
        await self.mysql.require_schema(*schema_contract(TABLES))
        return {"etf.fundamentals.query": self}

    async def read(self, operation):
        def run():
            with self.mysql.read_engine.begin() as conn:
                return operation(conn)

        return await self.mysql.read(run)

    async def plan(
        self, source, *, codes=None, start=None, end=None, sample_dates=None, fresh=False
    ):
        if source == "ttjj":
            if sample_dates is not None:
                raise ValueError("ETF净值抽样使用完整证券或区间")
            catalog = await self.directory.catalog(codes)
            return await self.read(
                lambda conn: nav_plan(
                    conn, self.namespace, catalog, start=start, end=end, fresh=fresh
                )
            )
        if source not in ("sse", "szse") or codes is not None:
            raise ValueError("ETF份额按完整来源日期采集，不能截断证券集合")
        return await self.read(
            lambda conn: share_plan(
                conn,
                self.namespace,
                source,
                start=start,
                end=end,
                sample_dates=sample_dates,
                fresh=fresh,
            )
        )

    async def browse(
        self, source="ttjj", code="", start="", end="", after=None, limit=200, order=None
    ):
        import re

        if source not in ("sse", "szse", "ttjj") or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("ETF查询来源或分页上限无效")
        if code and (
            not isinstance(code, str) or not re.fullmatch(r"[0-9]{1,6}(?:\.(SH|SZ))?", code)
        ):
            raise ValueError("ETF预览代码筛选无效")
        if start:
            day(start)
        if end:
            day(end)
        if start and end and start > end:
            raise ValueError("ETF预览起止倒置")
        nav = source == "ttjj"
        table, stamp = ("etf_daily_nav", "nav_date") if nav else ("etf_daily_share", "share_date")
        fields = (
            ("unified_code", stamp, *NAV_FIELDS, "version_observed_at")
            if nav
            else (
                "unified_code",
                stamp,
                "source",
                "name",
                "total_shares",
                "source_group",
                "source_type",
                "version_observed_at",
            )
        )
        args = dict(
            code=code + "%", start=start or "1900-01-01", end=end or "2100-12-31", source=source
        )

        def read(conn):
            rows, cursor = ordered_page(
                conn,
                "SELECT "
                + ",".join(fields)
                + " FROM "
                + table
                + " WHERE unified_code LIKE :code AND "
                + stamp
                + " BETWEEN :start AND :end"
                + ("" if nav else " AND source=:source"),
                args,
                fields=column_fields(fields),
                identity=(stamp, "unified_code"),
                order=order or {"field": stamp, "direction": "desc"},
                after=after,
                limit=limit,
            )
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, date):
                        r[k] = v.isoformat()
            return dict(rows=rows, next=cursor)

        return await self.read(read)

    async def stop(self):
        self.mysql = None

    def health(self):
        return dict(status="ok" if self.mysql else "stopped")

    async def check_sse(self, request=None):
        from empire.features.etf_fundamentals.preparation import checks

        return await checks(self, "sse", request)

    async def check_szse(self, request=None):
        from empire.features.etf_fundamentals.preparation import checks

        return await checks(self, "szse", request)

    async def check_ttjj(self, request=None):
        from empire.features.etf_fundamentals.preparation import checks

        return await checks(self, "ttjj", request)
