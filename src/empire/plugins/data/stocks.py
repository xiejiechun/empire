from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source, schema_contract
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.stocks import MARKET_NAMES
from empire.plugins.datasets.stocks import current_directory
from empire.plugins.infra.collection_state import read_state


class StockDataPlugin:
    preparation = (PreparationContribution(
        "universe", "stocks.query", "同花顺", "ths-stocks", "ths-universe-v1", "stock.universe.page",
        "collector.ths_universe", ("tests/test_ths_universe.py",), ("tests/integration/test_ths_stock_archive.py",)),)

    manifest = PluginManifest(
        "data.stocks", "股票列表查询", requires=("mysql.store",),
        provides=("stocks.query", "stocks.schema"),
        description="查询唯一一份当前股票列表；未完成采集不会覆盖当前列表",
    )

    def __init__(self, namespace: str = "empire", source: str = "sina",
                 job_key: str = "ths-universe-v1", project_id: str = "current"):
        self.mysql = None
        self.namespace = namespace
        self.source = source
        self.job_key = job_key
        self.project_id = project_id

    async def start(self, context: PluginContext) -> dict:
        self.mysql = context.get("mysql.store")
        require_fixed_source('stock', self.source)
        await self.mysql.require_schema(*schema_contract('stock', 'name'))
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
            state = (current_directory(connection, self.namespace) if self.project_id == 'current'
                     else read_state(connection, self.namespace, self.project_id, self.source))
            snapshot = state.get("publication")
            if not snapshot:
                return {"snapshot": None, "total": 0, "rows": [], "offset": 0, "limit": limit}
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params = {"source": state.get('source', self.source), "search": pattern, "offset": offset, "limit": limit}
            where = ("(CONVERT(unified_code USING utf8mb4) LIKE :search "
                     "OR name LIKE :search OR CONVERT(CONCAT(LOWER(RIGHT(unified_code,2)),LEFT(unified_code,6)) USING utf8mb4) LIKE :search)")
            if market is not None:
                where += " AND RIGHT(unified_code,2)=:market"
                params["market"] = market
            total = connection.execute(text(f"SELECT COUNT(*) FROM stock WHERE {where}"), params).scalar_one()
            rows = connection.execute(text(f"""
                SELECT :source AS source, LEFT(unified_code,6) AS code, name, unified_code, RIGHT(unified_code,2) AS market, CONCAT(LOWER(RIGHT(unified_code,2)),LEFT(unified_code,6)) AS source_symbol
                FROM stock WHERE {where} ORDER BY unified_code LIMIT :limit OFFSET :offset
            """), params).mappings().all()
            return {"snapshot": {k: str(v) if hasattr(v, "isoformat") else v for k, v in snapshot.items()},
                    "total": total, "rows": [dict(row) for row in rows], "offset": offset, "limit": limit}

    async def preparation_check(self):
        from empire.plugins.data.preparation_checks import check_stocks
        return await self.mysql.read(check_stocks, self)

    async def candidates(self, search='', dataset='stock', limit=20):
        from empire.plugins.data.preview_candidates import candidates
        return await candidates(self.mysql, search, dataset, limit)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
