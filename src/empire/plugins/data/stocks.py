import json
from datetime import datetime

from sqlalchemy import text

from empire.contracts.plugin import PluginContext, PluginManifest
from empire.contracts.stocks import MARKET_NAMES


class StockDataPlugin:
    manifest = PluginManifest(
        "data.stocks", "股票列表查询", requires=("mysql.store", "redis.store"), provides=("stocks.query",),
        description="查询唯一一份当前股票列表；未完成采集不会覆盖当前列表",
    )

    def __init__(self, source: str = "sina"):
        self.mysql = self.redis = None
        self.source = source

    async def start(self, context: PluginContext) -> dict:
        self.mysql = context.get("mysql.store")
        self.redis = context.get("redis.store")
        return {"stocks.query": self}

    async def list_stocks(self, search: str = "", offset: int = 0, limit: int = 200,
                          market: str | None = None) -> dict:
        if not 1 <= limit <= 500 or not 0 <= offset <= 100000 or len(search) > 100:
            raise ValueError("Invalid stock-list query bounds")
        if market is not None and market not in MARKET_NAMES:
            raise ValueError("不支持的股票市场，请选择 SH、SZ 或 BJ")
        confirmed = await self.redis.client.get(f"{self.redis.prefix}:stocks:committed:{self.source}")
        result = await self.mysql.read(self._list, search.strip(), offset, limit, market)
        if confirmed and result["snapshot"]:
            marker = json.loads(confirmed)
            if datetime.fromisoformat(marker["started_at"]) >= datetime.fromisoformat(result["snapshot"]["started_at"]):
                result["verified_snapshot_id"] = marker["snapshot_id"]
        return result

    def _list(self, search, offset, limit, market=None):
        with self.mysql.engine.connect() as connection:
            snapshot = connection.execute(text("""
                SELECT generation AS snapshot_id, MIN(started_at) AS started_at,
                       MAX(updated_at) AS finished_at, COUNT(*) AS row_count
                FROM stock WHERE source=:source GROUP BY generation
            """), {"source": self.source}).mappings().first()
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
                SELECT code, name, unified_code, market, source_symbol
                FROM stock WHERE {where} ORDER BY unified_code LIMIT :limit OFFSET :offset
            """), params).mappings().all()
            return {"snapshot": {k: str(v) if hasattr(v, "isoformat") else v for k, v in snapshot.items()},
                    "total": total, "rows": [dict(row) for row in rows], "offset": offset, "limit": limit}

    async def batch_status(self, snapshot_id: str) -> dict | None:
        confirmed = await self.redis.client.get(f"{self.redis.prefix}:stocks:committed:{self.source}")
        if confirmed:
            value = json.loads(confirmed)
            if value["snapshot_id"] == snapshot_id:
                return value
            result = await self.redis.client.get(f"{self.redis.prefix}:stocks:result:{self.source}")
            value = json.loads(result) if result else None
            return value if value and value["snapshot_id"] == snapshot_id and value["status"] == "invalid" else None
        def read():
            with self.mysql.engine.connect() as connection:
                count = connection.execute(text("""
                    SELECT COUNT(*) FROM stock WHERE source=:source AND generation=:id
                """), {"source": self.source, "id": snapshot_id}).scalar_one()
                return {"status": "complete", "row_count": count, "expected_count": count,
                        "error_text": ""} if count else None
        committed = await self.mysql.read(read)
        if committed:
            return committed
        result = await self.redis.client.get(f"{self.redis.prefix}:stocks:result:{self.source}")
        value = json.loads(result) if result else None
        return value if value and value["snapshot_id"] == snapshot_id and value["status"] == "invalid" else None

    async def stop(self):
        self.mysql = self.redis = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
