"""Independent MySQL-only browsing and product-specific coverage acceptance."""
import json
from datetime import date

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, capability, project
from empire.plugins.data.kaipanla_scope import MarketDayScope
from empire.plugins.datasets.kaipanla_products import KEYS, TABLES, digest, validate


class KaipanlaProductDataPlugin(MarketDayScope):
    def __init__(self, kind, namespace='empire'):
        super().__init__(namespace=namespace)
        self.kind, self.project_id = kind, project(kind)
        item = PRODUCTS[kind]
        self.manifest = PluginManifest('data.kaipanla_' + kind, '开盘啦' + item.title + '查询',
            requires=('mysql.store',), provides=(capability(kind),), description=item.note)
        self.preparation = (PreparationContribution(item.requirement, capability(kind), '开盘啦',
            self.project_id, self.project_id + '-v1', 'kaipanla.' + kind + '.day',
            'collector.kaipanla_' + kind, ('tests/test_kaipanla_products.py',),
            ('tests/integration/test_kaipanla_products_archive.py',), scoped=True),)

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(TABLES, KEYS)
        return {capability(self.kind): self}

    def _records(self, conn, market, code, start, end):
        return [dict(r) for r in conn.execute(text(
            'SELECT trade_date,payload,content_hash,version_observed_at FROM stock_market_day '
            'WHERE kind=:kind AND unified_code=:security AND trade_date BETWEEN :start AND :end '
            'ORDER BY trade_date LIMIT 10001'), dict(kind=self.kind, security=code + '.' + market,
                                                    start=start, end=end)).mappings()]

    def _decode(self, stored, market, code):
        row = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
        validate(row, self.kind)
        if (row['market'], row['code'], row['trade_date']) != (market, code, stored['trade_date'].isoformat()):
            raise ValueError('证券日关联错误')
        if digest(row) != stored['content_hash']:
            raise ValueError('内容摘要错误')
        return row

    def _covered(self, market, code, start, end, lifecycle=None):
        with self.mysql.read_engine.connect() as conn:
            records = self._records(conn, market, code, start, end)
        if len(records) > 10000:
            raise ValueError('证券日覆盖核验超限')
        covered = set()
        for stored in records:
            try:
                row = self._decode(stored, market, code)
                if lifecycle is None or lifecycle == row['lifecycle']:
                    covered.add(stored['trade_date'])
            except (ValueError, KeyError, TypeError):
                continue
        return covered

    async def day(self, market, code, trade_date):
        from empire.contracts.security import unified_code
        unified_code(market, code)
        day = date.fromisoformat(trade_date)
        def read():
            with self.mysql.read_engine.connect() as conn:
                records = self._records(conn, market, code, day, day)
            if not records:
                return None
            return dict(data=self._decode(records[0], market, code),
                        observed_at=records[0]['version_observed_at'])
        return await self.mysql.read(read)

    async def preparation_check(self, request=None):
        from empire.plugins.data.kaipanla_products_preparation import audit
        return await audit(self, request)
