"""Explicit node-profile maintenance; never starts collectors or an archiver."""
import argparse
import asyncio
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from empire.bootstrap import (
    DownloadSettingsPlugin,
    HttpPlugin,
    MySQLPlugin,
    PluginManager,
    ProxyPoolPlugin,
    RecordsPlugin,
    Redactor,
    RedisPlugin,
)
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore
from empire.sources.yuanhang_client import fetch_history, provision_guest
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService, YuanhangIdentityPlugin


def manager_for(config):
    groups = dict(config['rate_groups'])
    groups.setdefault('ths', dict(domains=['10jqka.com.cn'], min_interval_ms=2000))
    plugins = [RedisPlugin(config['redis']), MySQLPlugin(config['mysql']),
               RecordsPlugin(secrets=tuple(config.get(k, {}).get('password', '') for k in ('redis', 'mysql'))),
               ProxyPoolPlugin(), DownloadSettingsPlugin(), HttpPlugin(groups, config.get('http', {})),
               YuanhangIdentityPlugin()]
    for plugin in plugins:
        plugin.manifest = replace(plugin.manifest, autostart=True)
    return PluginManager(plugins, redactor=Redactor.from_config(config))


async def run(args):
    config = load_config(args.config)
    manager = manager_for(config)
    counts, report = {}, {'schema': 1, 'business_rows_written': 0, 'registration_requests': 0}
    pool = None
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    report['routes'] = counts
    try:
        await manager.start('infra.http')
        registry = ProfileRegistry(SettingsStore(manager.registry.get('mysql.store'), config['redis']['namespace']),
                                   WindowsProtection())
        pool = manager.registry.get('proxy.pool')
        snapshot = await pool.snapshot()
        online = sorted(d['code'] for d in snapshot['devices'] if d['remaining_seconds'] > 0)
        report['online_nodes'] = online
        if args.watch_seconds:
            before = counts.get('proxy_requests', 0)
            await manager.start('source.yuanhang_identity')
            await asyncio.sleep(args.watch_seconds)
            report['identity_service'] = manager.registry.get('yuanhang.identity').health()
            report['registration_requests'] = counts.get('proxy_requests', 0) - before
            await manager.stop('source.yuanhang_identity')
        profiles = await registry.ensure(online) if args.initialize else await registry.load()
        if args.provision:
            code = args.provision
            if code not in online or code not in profiles:
                raise ValueError('Node must be online and have an initialized durable profile')
            report['target_node'] = code
            http = manager.registry.get('http.fetch')
            first_request = profiles[code].registration == 'unrequested'
            before = counts.get('proxy_requests', 0)
            try:
                await provision_guest(http, registry, code, project_id='ths-yuanhang-research')
            finally:
                if first_request:
                    report['registration_requests'] = counts.get('proxy_requests', 0) - before
            service = IdentityService(registry, pool, http, manager.registry.get('collection.records'))
            try:
                session = await service.login(code, project_id='ths-yuanhang-research')
            finally:
                await service.close()
            report['login_verified'] = True
            if args.verify_through:
                snapshot = await fetch_history(http, session, unified_code='301718.SZ', dataset='daily',
                                               start=date(1990, 1, 1), end=args.verify_through)
                rows = snapshot.data
                report['native_verification'] = dict(code='301718.SZ', count=len(rows),
                    first=rows[0].trade_date.isoformat(), last=rows[-1].trade_date.isoformat())
            profiles = await registry.load()
        report['profiles'] = {code: dict(profile_id=p.profile_id, registration=p.registration,
                                         provisioned=p.provisioned) for code, p in profiles.items()}
    except Exception as exc:
        report['failure'] = dict(type=type(exc).__name__, stage=getattr(exc, 'stage', None),
                                 code=getattr(exc, 'code', None))
    finally:
        if pool is not None:
            report['node_request_counts'] = {code: entry.requests for code, entry in pool.entries.items()
                                             if entry.requests}
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        with args.report.open('x', encoding='utf8') as output:
            output.write(serialized)
    print(serialized)
    return 1 if 'failure' in report else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--initialize', action='store_true', help='Persist profiles for currently online nodes')
    parser.add_argument('--watch-seconds', type=int, default=0,
                        help='Run the actual automatic identity plugin for 5–300 seconds; may provision new nodes')
    parser.add_argument('--provision', help='One node code; one initial application, then normal existing login')
    parser.add_argument('--verify-through', type=date.fromisoformat, help='Verify native sample through a completed day')
    parser.add_argument('--report', type=Path, help='New metadata-only evidence file; never overwrites')
    args = parser.parse_args()
    if args.watch_seconds and (not 5 <= args.watch_seconds <= 300 or args.initialize or args.provision):
        parser.error('--watch-seconds requires 5–300 seconds and cannot combine with --initialize/--provision')
    if args.report and (args.report.exists() or not args.report.parent.is_dir()):
        parser.error('Report must be a new file in an existing directory')
    if args.verify_through and not args.provision:
        parser.error('--verify-through requires --provision')
    raise SystemExit(asyncio.run(run(args)))
