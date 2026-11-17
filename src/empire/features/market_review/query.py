"""Read-only review service over existing archived business data."""
from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.features.market_review.reading import read_review


class ReviewQuery:
    manifest = PluginManifest('data.market_review', '市场复盘查询', requires=('mysql.store',),
                              provides=('market.review.query',))

    def __init__(self, namespace='empire'):
        self.namespace = namespace

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        return {'market.review.query': self}

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if getattr(self, 'mysql', None) else 'stopped'}

    async def review(self, start, end):
        return await self._snapshot(lambda conn: read_review(conn, start, end))

    async def market(self, date):
        from .market import read_market
        return await self._snapshot(lambda conn: read_market(conn, date, namespace=self.namespace))

    async def _snapshot(self, reader):
        def operation():
            with self.mysql.read_engine.connect() as conn:
                conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
                conn.execute(text('START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT'))
                try:
                    return reader(conn)
                finally:
                    conn.rollback()
        return await self.mysql.read(operation)
