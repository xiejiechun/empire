

from empire.contracts.plugin import PluginManifest
from empire.plugins.infra.collection_state import CollectionState


class ArchiveConfirmationPlugin:
    manifest = PluginManifest(
        "infra.archive_confirmation", "归档完成确认",
        requires=("mysql.store", "redis.store"), provides=("archive.confirmation",),
        description="供采集器确认 Redis 队列已由统一归档器提交；缓存异常时回源 MySQL",
    )

    def __init__(self, handlers=None):
        self.handlers = dict(handlers or {})
        if not all(callable(handler) for handler in self.handlers.values()):
            raise ValueError('归档确认处理器必须可调用')
        self.mysql = self.redis = None

    async def start(self, context):
        self.mysql = context.get("mysql.store")
        self.redis = context.get("redis.store")
        return {"archive.confirmation": self}

    async def stock_status(self, source, job_key, project_id, snapshot_id):
        handler = self.handlers.get('stocks.snapshot')
        if handler is None:
            raise RuntimeError('股票归档确认处理器未通过业务贡献注入')
        return await handler(self.mysql, self.redis, source, job_key, project_id, snapshot_id)

    async def page_status(self, source, job_key, project_id, batch_id, page):
        return await CollectionState(self.mysql, self.redis.prefix).page_status(
            self.redis, source, job_key, project_id, batch_id, page)

    async def stop(self):
        self.mysql = self.redis = None

    def health(self):
        return {"status": "ok" if self.mysql and self.redis else "stopped"}



