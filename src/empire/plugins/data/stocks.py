from sqlalchemy import text

from empire.contracts.plugin import PluginContext, PluginManifest
from empire.contracts.stocks import MARKET_NAMES
from empire.plugins.infra.collection_state import read_state


class StockDataPlugin:
    manifest = PluginManifest(
        "data.stocks", "股票列表查询", requires=("mysql.store",),
        provides=("stocks.query", "stocks.schema"),
        description="查询唯一一份当前股票列表；未完成采集不会覆盖当前列表",
    )

    def __init__(self, namespace: str = "empire", source: str = "sina",
                 job_key: str = "sina-universe-v1", project_id: str = "sina-stocks"):
        self.mysql = None
        self.namespace = namespace
        self.source = source
        self.job_key = job_key
        self.project_id = project_id

    async def start(self, context: PluginContext) -> dict:
        self.mysql = context.get("mysql.store")
        await self.mysql.require_schema({"stock": {
            "source", "node", "unified_code", "code", "name", "market", "source_symbol",
        }}, {"stock": ["source", "unified_code"]})
        return {"stocks.query": self, "stocks.schema": self}

    async def list_stocks(self, search: str = "", offset: int = 0, limit: int = 200,
                          market: str | None = None) -> dict:
        if not 1 <= limit <= 500 or not 0 <= offset <= 100000 or len(search) > 100:
            raise ValueError("Invalid stock-list query bounds")
        if market is not None and market not in MARKET_NAMES:
            raise ValueError("不支持的股票市场，请选择 SH、SZ 或 BJ")
        return await self.mysql.read(self._list, search.strip(), offset, limit, market)

    def _list(self, search, offset, limit, market=None):
        with self.mysql.read_engine.connect() as connection:
            state = read_state(connection, self.namespace, self.project_id, self.source)
            snapshot = state.get("publication")
            if not snapshot:
                return {"snapshot": None, "total": 0, "rows": [], "offset": 0, "limit": limit}
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params = {"source": self.source, "search": pattern, "offset": offset, "limit": limit}
            where = ("source=:source AND (CONVERT(unified_code USING utf8mb4) LIKE :search "
                     "OR name LIKE :search OR CONVERT(source_symbol USING utf8mb4) LIKE :search)")
            if market is not None:
                where += " AND market=:market"
                params["market"] = market
            total = connection.execute(text(f"SELECT COUNT(*) FROM stock WHERE {where}"), params).scalar_one()
            rows = connection.execute(text(f"""
                SELECT source, code, name, unified_code, market, source_symbol
                FROM stock WHERE {where} ORDER BY unified_code LIMIT :limit OFFSET :offset
            """), params).mappings().all()
            return {"snapshot": {k: str(v) if hasattr(v, "isoformat") else v for k, v in snapshot.items()},
                    "total": total, "rows": [dict(row) for row in rows], "offset": offset, "limit": limit}

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
