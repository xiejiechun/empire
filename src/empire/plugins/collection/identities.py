"""Platform-scoped identity query catalog. Reading never starts authentication."""
from empire.contracts.plugin import PluginManifest


class IdentityQueries:
    def __init__(self, platforms):
        self.platforms = {p.id: p for p in platforms}
        if len(self.platforms) != len(platforms):
            raise ValueError('Duplicate identity platform')

    async def catalog(self):
        return [dict(id=p.id, name=p.name, plugin_id=p.plugin_id) for p in self.platforms.values()]

    async def snapshot(self, platform, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid identity page')
        if platform not in self.platforms:
            raise ValueError('Unknown identity platform')
        return await self.platforms[platform].snapshot(offset, limit)


class IdentityQueryPlugin:
    manifest = PluginManifest('collection.identities', '平台身份查询',
        requires=('mysql.store', 'redis.store', 'collection.records'), provides=('identities.query',),
        description='按平台读取身份参数和最近运行结果；查询不申请或登录账号')

    def __init__(self, factories):
        self.factories = factories

    async def start(self, context):
        self.query = IdentityQueries([factory(context) for factory in self.factories])
        return {'identities.query': self.query}

    async def stop(self):
        self.query = None

    def health(self):
        return {}
