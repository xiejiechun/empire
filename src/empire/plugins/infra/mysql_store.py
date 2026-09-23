from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from sqlalchemy import URL, create_engine, inspect, text

from empire.contracts.plugin import PluginContext, PluginManifest
from empire.core.config import project_root


def make_engine(settings: dict):
    return create_engine(URL.create(
        "mysql+pymysql", username=settings["user"], password=settings.get("password"),
        host=settings.get("host", "127.0.0.1"), port=int(settings.get("port", 3306)),
        database=settings["database"], query={"charset": "utf8mb4"},
    ), pool_size=2, max_overflow=0, pool_pre_ping=True,
        connect_args={"connect_timeout": settings.get("connect_timeout", 5),
                      "read_timeout": 20, "write_timeout": 20,
                      "init_command": "SET time_zone = '+00:00'"})


def initialize_database(settings: dict) -> None:
    engine = make_engine(settings)
    try:
        sql = (project_root() / "sql" / "schema.sql").read_text(encoding="utf-8")
        sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        with engine.begin() as connection:
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
    finally:
        engine.dispose()


REQUIRED_COLUMNS = {
    "stock": {"source", "node", "unified_code", "code", "name", "market", "source_symbol",
              "generation", "started_at", "updated_at"},
}


class MySQLPlugin:
    manifest = PluginManifest(
        "infra.mysql", "MySQL 持久化", provides=("mysql.store",),
        description="启动仅检查结构；归档事务支持重复投递去重",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.engine = None
        self.executor = None
        self.inflight: set[asyncio.Future] = set()
        self.stats = {"status": "stopped"}

    async def start(self, context: PluginContext) -> dict:
        self.engine = make_engine(self.settings)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="empire-mysql")
        version = await self._call(self._validate)
        self.stats = {"status": "ok", "version": version,
                      "database": self.settings["database"], "transactions": 0}
        return {"mysql.store": self}

    def _validate(self) -> str:
        with self.engine.connect() as conn:
            metadata = inspect(conn)
            tables = set(metadata.get_table_names())
            for name, required in REQUIRED_COLUMNS.items():
                if name not in tables:
                    raise RuntimeError(f"缺少表 {name}，请显式执行 empire init-db；启动不会自动改库")
                columns = {c["name"] for c in metadata.get_columns(name)}
                if not required <= columns:
                    raise RuntimeError(f"表 {name} 缺少字段 {sorted(required - columns)}")
                primary = metadata.get_pk_constraint(name)["constrained_columns"]
                if primary != ["source", "unified_code"]:
                    raise RuntimeError(f"表 {name} 的幂等主键不兼容")
                options = metadata.get_table_options(name)
                if str(options.get("mysql_engine", "")).lower() != "innodb":
                    raise RuntimeError(f"表 {name} 必须使用 InnoDB 事务引擎")
            return str(conn.execute(text("SELECT VERSION()")).scalar_one())

    async def _call(self, operation, *args):
        future = asyncio.get_running_loop().run_in_executor(self.executor, partial(operation, *args))
        self.inflight.add(future)
        future.add_done_callback(self.inflight.discard)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # The worker thread may have committed. Wait for its real outcome before closing it.
            try:
                await asyncio.shield(future)
            except Exception:
                pass
            raise

    async def archive(self, records: list[dict]) -> list[dict]:
        """Commit only business writes. Redis ownership is handled by the archive plugin."""
        try:
            result = await self._call(self._archive, records)
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
        """Run an internal data plugin's query on the bounded SQL worker."""
        return await self._call(operation, *args)

    async def stop(self) -> None:
        if self.inflight:
            await asyncio.gather(*(asyncio.shield(f) for f in list(self.inflight)), return_exceptions=True)
        if self.engine:
            await asyncio.to_thread(self.engine.dispose)
            self.engine = None
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return dict(self.stats)
