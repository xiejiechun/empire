"""Credential-free Yuanhang projection for the platform identity catalog."""
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.settings import SettingsStore
from empire.sources.yuanhang_auth import VERSION
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import PROJECT


class YuanhangManagement:
    id, name, plugin_id = 'ths-yuanhang', '同花顺远航版', 'source.yuanhang_identity'

    def __init__(self, context):
        self.context = context
        self.registry = ProfileRegistry(SettingsStore(context.get('mysql.store'),
            context.get('redis.store').prefix), WindowsProtection())
        self.records = context.get('collection.records')

    async def snapshot(self, offset, limit):
        service = self.context.optional('yuanhang.identity')
        health = service.health() if service else {}
        active = {r['id']: r for r in health.get('active_runs', [])}
        warning = []
        try:
            profiles = await service.get_profiles() if service else await self.registry.load()
        except Exception:
            profiles = {}
            warning.append('身份配置读取失败；可能需显式迁移或无法解密，原档案保留')
        try:
            history = await self.records.list_identity_runs(PROJECT)
        except Exception:
            history = []
            warning.append('Redis运行记录读取失败，不能判断上轮结果')
        # Records are ordered by completion/last write, not source timestamps.
        completed = [r for r in history if r['status'] != 'running']
        last_by_code = {}
        for row in completed:
            last_by_code.setdefault(row['code'], row)
        unfinished = [dict(r, status='unconfirmed', message='操作未确认结束；程序可能中断')
                      for r in history if r['status'] == 'running' and r['id'] not in active]
        pool = self.context.optional('proxy.pool')
        online = service.online_codes() if service else set()
        if not service and pool:
            from time import monotonic
            online = {e.code for e in pool.entries.values() if e.expires > monotonic()}
        codes = sorted(profiles)
        offset = min(offset, max(0, (len(codes) - 1) // limit * limit))
        rows = []
        for code in codes[offset:offset + limit]:
            profile = profiles[code]
            rows.append(dict(code=code, profile_id=profile.profile_id, registration=profile.registration,
                rejection_code=profile.rejection_code, online=code in online,
                creation=dict(profile.creation), last_run=last_by_code.get(code),
                current=[r for r in active.values() if r['code'] == code],
                unconfirmed=[r for r in unfinished if r['code'] == code]))
        return dict(platform=self.id, running=service is not None, rows=rows, total=len(codes), offset=offset,
                    current=list(active.values()), last_run=completed[0] if completed else None,
                    unconfirmed=unfinished, history=history, protocol_version=VERSION,
                    warning='；'.join(warning), health=health)
