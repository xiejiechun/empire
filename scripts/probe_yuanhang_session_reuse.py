"""Bounded read-only native reuse probe; no provisioning, collector or archiver."""
import asyncio
import json
from datetime import date
from pathlib import Path

from yuanhang_node_profiles import manager_for

from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore
from empire.sources import yuanhang_client
from empire.sources.yuanhang_client import fetch_history
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService


async def run(output, idle_seconds=0):
    cfg = load_config()
    manager = manager_for(cfg)
    identity = None
    counts, report = {}, {'passed': False, 'business_writes': 0, 'registration_requests': 0}
    decode = yuanhang_client.decode_response
    def inspect(body, **kwargs):
        try:
            return decode(body, **kwargs)
        except ValueError:
            import hashlib
            report['invalid_frame'] = dict(length=len(body), sha256=hashlib.sha256(body).hexdigest(),
                all_zero=bool(body) and not any(body))
            raise
    yuanhang_client.decode_response = inspect
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(counts)
    try:
        await manager.start('infra.http')
        http, pool = (manager.registry.get(k) for k in ('http.fetch', 'proxy.pool'))
        await pool.snapshot()
        registry = ProfileRegistry(SettingsStore(manager.registry.get('mysql.store'),
            cfg['redis']['namespace']), WindowsProtection())
        identity = IdentityService(registry, pool, http)
        profiles = await registry.load()
        nodes = sorted(n for n in identity.online_codes() if n in profiles and profiles[n].provisioned)
        if not nodes:
            raise ValueError('No online provisioned node')
        node = nodes[0]
        report['node'] = node
        report['samples'] = []
        session = None
        for dataset, code in [('daily', '000001.SZ'), ('financial', '000001.SZ'), ('daily', '920200.BJ')]:
            current = await identity.login(node, project_id='ths-yuanhang-research')
            if session is not None and current is not session:
                raise AssertionError('Cross-project session changed')
            session = current
            snapshot = await fetch_history(http, session, unified_code=code, dataset=dataset,
                start=date(1900, 1, 1), end=date(2100, 12, 31) if dataset == 'financial' else date(2026, 10, 30),
                max_retries=0)
            report['samples'].append(dict(code=code, dataset=dataset,
                response_bytes=snapshot.response_bytes, decoded_bytes=snapshot.decoded_bytes))
            if idle_seconds and len(report['samples']) == 1:
                await asyncio.sleep(idle_seconds)
        report['sessions'] = dict(identity.sessions.stats)
        report['connections'] = dict(http.native_connections.stats)
        if report['sessions']['logins'] != 1 or report['connections']['opened'] != 1:
            raise AssertionError('Expected one authentication and one native connection')
        report['passed'] = True
    except Exception as exc:
        report['failure'] = dict(type=type(exc).__name__, stage=getattr(exc, 'stage', None),
            code=getattr(exc, 'code', None))
    finally:
        yuanhang_client.decode_response = decode
        if identity:
            await identity.close()
        await manager.shutdown()
        report['routes'] = counts
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        with Path(output).open('x', encoding='utf8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--idle-seconds', type=int, choices=range(61), default=0)
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error('Output must be new')
    asyncio.run(run(args.output, args.idle_seconds))
