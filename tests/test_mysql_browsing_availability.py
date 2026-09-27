import pytest

from empire.contracts.plugin import PluginManifest
from empire.core.manager import DependencyError, PluginManager
from empire.plugins.data.news import NewsDataPlugin
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin


class FakeMysql:
    def __init__(self, missing_table=None):
        self.missing_table = missing_table

    async def require_schema(self, columns_by_table, primary_keys):
        if self.missing_table in columns_by_table:
            raise RuntimeError(f"missing table {self.missing_table}")

    async def read(self, operation, *args):
        if operation.__name__ == "_list" and len(args) == 4:
            return {"snapshot": {"snapshot_id": "sql-publication"}, "total": 1,
                    "rows": [{"code": "000001"}], "offset": 0, "limit": args[2]}
        if operation.__name__ == "_list":
            return {"total": 1, "rows": [{"news_id": 1}], "limit": args[1],
                    "anchor": None, "next_cursor": None}
        if operation.__name__ == "_month":
            return {"month": args[0], "rows": [{"trade_date": args[0] + "-01"}],
                    "expected_count": 30, "complete": False}
        raise AssertionError(f"unexpected read operation: {operation.__name__}")


class MysqlProvider:
    manifest = PluginManifest("test.mysql", "MySQL", provides=("mysql.store",))

    def __init__(self, store=None):
        self.store = store or FakeMysql()

    async def start(self, context):
        return {"mysql.store": self.store}

    async def stop(self):
        pass

    def health(self):
        return {"status": "ok"}


class FailingRedisProvider:
    manifest = PluginManifest("test.redis", "Redis", provides=("redis.store",))

    def __init__(self):
        self.available = False

    async def start(self, context):
        if not self.available:
            raise ConnectionError("redis unavailable")
        return {"redis.store": self}

    async def stop(self):
        pass

    def health(self):
        return {"status": "error"}


async def test_archived_mysql_data_remains_browsable_when_redis_is_unavailable():
    redis = FailingRedisProvider()
    manager = PluginManager([
        MysqlProvider(), redis, ArchiveConfirmationPlugin(),
        StockDataPlugin("empire:test"), NewsDataPlugin(), CalendarDataPlugin(),
    ])
    await manager.start("data.stocks")
    await manager.start("data.news")
    await manager.start("data.trade_calendar")

    stocks = await manager.registry.get("stocks.query").list_stocks()
    news = await manager.registry.get("news.query").list_news()
    calendar = await manager.registry.get("calendar.query").month("2026-09")
    assert stocks["snapshot"]["snapshot_id"] == "sql-publication"
    assert "verified_snapshot_id" not in stocks
    assert news["rows"][0]["news_id"] == 1
    assert calendar["rows"][0]["trade_date"] == "2026-09-01"

    with pytest.raises(DependencyError, match="redis unavailable"):
        await manager.start("infra.archive_confirmation")
    states = {item["id"]: item["state"] for item in manager.snapshot()["plugins"]}
    assert states["data.stocks"] == states["data.news"] == states["data.trade_calendar"] == "RUNNING"
    assert states["infra.archive_confirmation"] == "BLOCKED"

    queries = {name: manager.registry.get(name) for name in (
        "stocks.query", "news.query", "calendar.query")}
    redis.available = True
    await manager.start("infra.archive_confirmation")
    assert all(manager.registry.get(name) is value for name, value in queries.items())
    assert manager.entries["infra.archive_confirmation"].state == "RUNNING"
    await manager.shutdown()


async def test_unrelated_business_table_failure_only_blocks_its_data_plugin():
    mysql = FakeMysql(missing_table="finance_news")
    manager = PluginManager([
        MysqlProvider(mysql), StockDataPlugin("empire:test"), NewsDataPlugin(), CalendarDataPlugin(),
    ])
    await manager.start("data.stocks")
    await manager.start("data.trade_calendar")
    with pytest.raises(RuntimeError, match="finance_news"):
        await manager.start("data.news")
    assert manager.entries["data.stocks"].state == "RUNNING"
    assert manager.entries["data.trade_calendar"].state == "RUNNING"
    assert manager.entries["data.news"].state == "FAILED"
    await manager.shutdown()
