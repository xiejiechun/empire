"""Formal observation query entry point."""
from empire.contracts.plugin import PluginManifest

from .reading import catalog, read_base


async def read(registry, month, index, market, settings=None, include_top=False, include_fx=(), include_turnover=False):
    if settings or include_top or include_fx or include_turnover:
        from .configured import configured_read
        return await configured_read(registry, month, index, market, settings or {}, include_top, include_fx, include_turnover)
    return await read_base(registry, month, index, market)


class ObservationQuery:
    manifest = PluginManifest('data.observation_calendar', '多指标观察查询',
        requires=('calendar.query', 'index.prices.query', 'market_margin.query', 'mysql.store', 'fx.daily.query'),
        provides=('observation.query',))

    async def start(self, context):
        self.context = context
        return {'observation.query': self}

    async def stop(self):
        self.context = None

    def health(self):
        return {'status': 'ok' if getattr(self, 'context', None) else 'stopped'}

    async def catalog(self):
        return await catalog(self.context)

    async def live(self, date, basis):
        from .intraday import read_live
        return await read_live(self.context, date, basis)

    async def month(self, month, index, market, settings=None, include_top=False, include_fx=(), include_turnover=False):
        return await read(self.context, month, index, market, settings, include_top, include_fx, include_turnover)
