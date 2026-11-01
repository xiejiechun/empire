"""Runtime discovery and durable guest provisioning over the shared proxy pool."""
import asyncio
from collections import Counter
from time import monotonic

from empire.contracts.plugin import PluginManifest
from empire.core.protected_values import WindowsProtection
from empire.plugins.collection.identity_runs import IdentityRuns
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.plugins.infra.settings import SettingsStore
from empire.sources.yuanhang_client import login_profile, provision_guest
from empire.sources.yuanhang_profiles import ProfileRegistry, node_code
from empire.sources.yuanhang_sessions import NodeSessions

PROJECT = 'ths-yuanhang-identity'
BLOCKED = {'requested', 'rejected', 'unknown'}


class IdentityService:
    def __init__(self, registry, pool, http, records=None):
        self.registry, self.pool, self.http = registry, pool, http
        self.profiles = {}
        self.error = ''
        self.current = None
        self.next_reload = 0
        self.closed = False
        self.lock = asyncio.Lock()
        self.inflight = set()
        self.runs = IdentityRuns(records, PROJECT)
        self.sessions = NodeSessions()

    def online_codes(self):
        # Consume the existing discovery cache; never scan RouterProxy again.
        now = monotonic()
        return {e.code for e in self.pool.entries.values()
                if e.expires > now and e.cooldown <= now}

    async def reload(self):
        self.profiles = await self.registry.load()
        self.sessions.prune(self.profiles)
        self.next_reload = monotonic() + 60

    async def reconcile(self):
        """One serialized pass; persisted intent arbitrates other processes too."""
        task = asyncio.current_task()
        self.inflight.add(task)
        tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False)
        try:
            async with self.lock:
                if self.closed:
                    return
                if monotonic() >= self.next_reload:
                    await self.reload()
                missing = self.online_codes() - self.profiles.keys()
                if missing:
                    self.profiles = await self.registry.ensure(missing)
                self.error = ''
                if any(p.registration in BLOCKED for p in self.profiles.values()):
                    return
                for code in sorted(self.online_codes()):
                    if self.closed:
                        return
                    profile = self.profiles[code]
                    if profile.provisioned or code not in self.online_codes():
                        continue
                    self.current = code
                    try:
                        async with self.runs.operation(code, 'application'):
                            self.profiles[code] = await provision_guest(
                                self.http, self.registry, code, project_id=PROJECT)
                        await self.reload()
                        if any(p.registration in BLOCKED for p in self.profiles.values()):
                            return
                    except Exception:
                        # Never retain exception text containing credentials. Reload
                        # durable intent before any later pass can send a request.
                        self.next_reload = 0
                        self.error = '首次申请未确认成功，已暂停自动申请；请检查持久状态'
                        await self.reload()
                        return
                    finally:
                        self.current = None
        except Exception:
            self.next_reload = 0
            self.error = '身份配置暂不可用，保留档案并暂停申请，等待恢复'
        finally:
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            self.inflight.discard(task)

    async def watch(self):
        while True:
            await self.reconcile()
            await asyncio.sleep(5)

    async def login(self, code, *, project_id, rejected=None):
        """Share node sessions across collectors and rounds, renewing on rejection.

        No speculative session expiry, background login or retry/registration on
        authentication failure. Every auth and later native request is node-bound.
        """
        node_code(code)
        if self.closed:
            raise RuntimeError('远航身份服务已停止')
        task = asyncio.current_task()
        self.inflight.add(task)
        tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False)
        try:
            profiles = await self.registry.load()
            profile = profiles.get(code)
            if profile is None or not profile.provisioned:
                raise ValueError('该节点身份尚未就绪，请查看远航节点身份服务状态')
            async def authenticate():
                async with self.runs.operation(code, 'login'):
                    return await login_profile(self.http, profile, project_id=project_id)
            return await self.sessions.get(code, profile, authenticate, rejected=rejected)
        finally:
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            self.inflight.discard(task)

    async def close(self):
        self.closed = True
        tasks = [t for t in self.inflight if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.profiles.clear()
        self.sessions.entries.clear()

    def health(self):
        blocked = {code: p.registration for code, p in self.profiles.items()
                   if p.registration in BLOCKED}
        return {'status': 'blocked' if blocked else 'error' if self.error else 'ok',
                'profiles': len(self.profiles), 'online': len(self.online_codes()),
                'states': dict(Counter(p.registration for p in self.profiles.values())),
                'applying': self.current, 'blocked_nodes': blocked,
                'automatic_application_paused': bool(blocked or self.error), 'error': self.error,
                'record_error': self.runs.error, 'active_runs': list(self.runs.active.values())}


class YuanhangIdentityPlugin:
    manifest = PluginManifest('source.yuanhang_identity', '远航节点身份',
        requires=('mysql.store', 'redis.store', 'proxy.pool', 'http.fetch', 'collection.records'),
        provides=('yuanhang.identity',),
        description='自动发现代理节点、持久建档、首次申请及固定账号复用；异常不重新注册')

    def __init__(self):
        self.service = self.monitor = None

    async def start(self, context):
        registry = ProfileRegistry(SettingsStore(context.get('mysql.store'),
            context.get('redis.store').prefix), WindowsProtection())
        self.service = IdentityService(registry, context.get('proxy.pool'), context.get('http.fetch'),
                                       context.get('collection.records'))
        try:
            await self.service.reload()
        except Exception:
            raise RuntimeError('远航身份配置读取失败；保留原配置，未开始申请') from None
        self.monitor = context.spawn(self.service.watch(), name='node-identities', critical=True)
        return {'yuanhang.identity': self.service}

    async def stop(self):
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
            self.monitor = None
        if self.service:
            await self.service.close()
            self.service = None

    def health(self):
        return self.service.health() if self.service else {}
