from __future__ import annotations

import asyncio

from sqlalchemy import URL, create_engine, inspect, text

from empire.contracts.plugin import PluginContext, PluginManifest
from empire.core.config import resource_root
from empire.plugins.infra.sql_lane import SQLLane, settle


def make_engine(settings: dict, *, pool_size=2):
    return create_engine(URL.create(
        "mysql+pymysql", username=settings["user"], password=settings.get("password"),
        host=settings.get("host", "127.0.0.1"), port=int(settings.get("port", 3306)),
        database=settings["database"], query={"charset": "utf8mb4"},
    ), pool_size=pool_size, max_overflow=0, pool_pre_ping=True,
        connect_args={"connect_timeout": settings.get("connect_timeout", 5),
                      "read_timeout": 20, "write_timeout": 20,
                      "init_command": "SET time_zone = '+08:00'"})


def initialize_database(settings: dict) -> None:
    engine = make_engine(settings)
    try:
        sql = (resource_root() / "sql" / "schema.sql").read_text(encoding="utf-8")
        sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        with engine.begin() as connection:
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
    finally:
        engine.dispose()


CORE_COLUMNS = {
    "app_setting": {"namespace", "kind", "setting_key", "payload", "updated_at"},
    "collection_state": {"namespace", "project_id", "source", "dataset", "payload", "updated_at"},
}
CORE_PRIMARY_KEYS = {
    "app_setting": ["namespace", "kind", "setting_key"],
    "collection_state": ["namespace", "project_id"],
}


def validate_tables(connection, columns_by_table, primary_keys):
    metadata = inspect(connection)
    tables = set(metadata.get_table_names())
    for name, required in columns_by_table.items():
        if name not in tables:
            raise RuntimeError(f"缺少表 {name}，请显式执行 empire init-db；启动不会自动改库")
        columns = {column["name"] for column in metadata.get_columns(name)}
        if not required <= columns:
            raise RuntimeError(f"表 {name} 缺少字段 {sorted(required - columns)}")
        primary = metadata.get_pk_constraint(name)["constrained_columns"]
        if primary != primary_keys[name]:
            raise RuntimeError(f"表 {name} 的幂等主键不兼容")
        options = metadata.get_table_options(name)
        if str(options.get("mysql_engine", "")).lower() != "innodb":
            raise RuntimeError(f"表 {name} 必须使用 InnoDB 事务引擎")


class MySQLPlugin:
    manifest = PluginManifest(
        "infra.mysql", "MySQL 持久化", provides=("mysql.store",),
        description="启动仅检查结构；归档事务支持重复投递去重",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.engine = None
        self.read_engine = None
        self.read_lane = self.control_lane = None
        self._stopping = None
        self.stats = {"status": "stopped"}

    async def start(self, context: PluginContext) -> dict:
        if self.engine is not None or self.read_lane is not None:
            raise RuntimeError("MySQL 已启动或正在关闭")
        self._stopping = None
        try:
            self.engine = make_engine(self.settings, pool_size=1)
            self.read_engine = make_engine(self.settings, pool_size=2)
            self.read_lane = SQLLane("empire-mysql-read", 2, 16)
            self.control_lane = SQLLane("empire-mysql-control", 1, 32)
            version = await self.control(self._validate)
        except BaseException:
            await self.stop()
            raise
        self.stats = {"status": "ok", "version": version,
                      "database": self.settings["database"], "transactions": 0}
        return {"mysql.store": self}

    def _validate(self) -> str:
        with self.engine.connect() as conn:
            validate_tables(conn, CORE_COLUMNS, CORE_PRIMARY_KEYS)
            return str(conn.execute(text("SELECT VERSION()")).scalar_one())

    async def require_schema(self, columns_by_table, primary_keys):
        def validate():
            with self.engine.connect() as connection:
                validate_tables(connection, columns_by_table, primary_keys)
        await self.control(validate)

    async def control(self, operation, *args):
        """Serialized writes and collection-critical reads, using engine (not read_engine)."""
        if self.control_lane is None:
            raise RuntimeError("MySQL 尚未启动")
        return await self.control_lane.call(operation, *args)

    async def archive(self, records: list[dict]) -> list[dict]:
        """Commit only business writes. Redis ownership is handled by the archive plugin."""
        try:
            result = await self.control(self._archive, records)
            self.stats.update(status="ok", error="")
            self.stats["transactions"] = self.stats.get("transactions", 0) + 1
            return result
        except Exception as exc:
            self.stats.update(status="degraded", error=str(exc))
            raise

    def _archive(self, records: list[dict]) -> list[dict]:
        with self.engine.begin() as conn:
            return [record["writer"](conn, record["envelope"], record["normalized"])
                    for record in records]

    async def read(self, operation, *args):
        """Browsing-only query; callbacks must use the isolated read_engine."""
        if self.read_lane is None:
            raise RuntimeError("MySQL 尚未启动")
        return await self.read_lane.call(operation, *args)

    async def stop(self) -> None:
        if self._stopping is None:
            for lane in (self.read_lane, self.control_lane):
                if lane:
                    lane.accepting = False
            self._stopping = asyncio.create_task(self._stop())
        await settle(self._stopping)

    async def _stop(self):
        await asyncio.gather(*(lane.close() for lane in (self.read_lane, self.control_lane) if lane))
        for engine in (self.read_engine, self.engine):
            if engine is not None:
                await asyncio.to_thread(engine.dispose)
        self.read_engine = self.engine = None
        self.read_lane = self.control_lane = None
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return {**self.stats, "lanes": {name: lane.health() for name, lane in (
            ("read", self.read_lane), ("control", self.control_lane)) if lane}}
