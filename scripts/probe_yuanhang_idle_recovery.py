"""One complete financial unit through shared proxy, fault recovery and private archive."""
import argparse
import asyncio
import copy
import json
from datetime import date
from pathlib import Path

from capacity_session import CapacitySession
from sqlalchemy import text
from verify_yuanhang_history import ReadOnlyIdentitySettings

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.sources import yuanhang_client
from empire.sources.yuanhang_coverage import financial_proofs
from empire.sources.yuanhang_payload import financial_payload
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService


async def collect(session, cfg, profiles):
    cfg = copy.deepcopy(cfg)
    source_namespace = cfg['redis']['namespace']
    cfg['mysql'] = session.settings
    cfg['redis']['namespace'] = 'empire:test:' + session.run_id
    initialize_database(cfg['mysql'])
    with session.source_engine.connect() as conn:
        session.require_source(conn)
        stocks = conn.execute(text("SELECT unified_code,name FROM stock WHERE unified_code='000001.SZ'")).mappings().all()
        calendar = conn.execute(text('SELECT trade_date,is_trade,updated_at FROM trade_calendar '
            "WHERE trade_date BETWEEN '2025-10-01' AND '2026-12-31' ORDER BY trade_date LIMIT 500")).mappings().all()
        sites = conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns "
            "AND kind='site' AND setting_key='ths'"), dict(ns=source_namespace)).mappings().all()
    with session.engine.begin() as conn:
        conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:unified_code,:name)'), [dict(r) for r in stocks])
        conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) '
            'VALUES(:trade_date,:is_trade,:updated_at)'), [dict(r) for r in calendar])
        for row in sites:
            conn.execute(text("INSERT INTO app_setting(namespace,kind,setting_key,payload) VALUES(:ns,'site',:key,:payload)"),
                dict(ns=cfg['redis']['namespace'], key=row['setting_key'], payload=row['payload']))
    manager = build_manager(cfg)
    identity = None
    class Registry:
        async def load(self):
            return profiles
    async def start(context):
        nonlocal identity
        identity = IdentityService(Registry(), context.get('proxy.pool'), context.get('http.fetch'))
        return {'yuanhang.identity': identity}
    async def stop():
        if identity:
            await identity.close()
    plugin = manager.entries['source.yuanhang_identity'].plugin
    plugin.start, plugin.stop = start, stop
    counts, injected, proofs = {}, False, None
    original = yuanhang_client.exchange_frame
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    try:
        await manager.start('collector.yuanhang_financial')
        c = manager.registry.get('collector.yuanhang_financial')
        c.selected_codes, c.request_retries = ['000001.SZ'], 2
        pool, http = (manager.registry.get(k) for k in ('proxy.pool', 'http.fetch'))
        await pool.snapshot()
        nodes = sorted(n for n in identity.online_codes() if n in profiles and profiles[n].provisioned)
        if not nodes:
            raise ValueError('No provisioned online node')
        _, through = await c.query.collection_scope(c.selected_codes)
        auth = await identity.login(nodes[0], project_id=c.project_id)
        await yuanhang_client.fetch_history(http, auth, unified_code='000001.SZ', dataset='daily',
            start=date(1900, 1, 1), end=date.fromisoformat(through), max_retries=0)

        async def exchange(channel, payload, *, allow_idle=False):
            nonlocal injected
            if not injected and allow_idle and channel.state.get('yuanhang_authenticated'):
                injected = True
                # Inject the exact known backlog once, on an actual reused
                # connection. The outbound request still uses shared routing;
                # its unread response is discarded when the socket retires.
                class Backlog:
                    async def write(self, data):
                        await channel.write(data)
                    async def readexactly(self, size):
                        return b'\xfd' * 4 + b'00000004\x09' if size == 13 else b'\0' * size
                return await original(Backlog(), payload, allow_idle=True)
            return await original(channel, payload, allow_idle=allow_idle)
        yuanhang_client.exchange_frame = exchange
        fetch = c.fetch
        async def capture(unit, **kwargs):
            nonlocal proofs
            snapshot = await fetch(unit, **kwargs)
            proofs = financial_proofs(financial_payload(snapshot, code=unit[0]))
            return snapshot
        c.fetch = capture
        result = await c.execute()
        problems = await c.query.audit_source_proofs('000001.SZ', proofs, financial=True)
        redis = manager.registry.get('redis.store')
        pending = await redis.client.xlen(redis.stream)
        before = dict(counts)
        await c.execute(baseline_revision=await c.checkpoint_revision())
        if (not injected or c.stats.get('idle_connection_retries') != 1 or problems or pending
                or counts != before or identity.sessions.stats['logins'] != 1
                or http.native_connections.stats['opened'] != 2):
            raise ValueError('Idle recovery/source/formal-query/repeat verification failed')
        session.report.update(sample=['000001.SZ'], sample_unit='complete joint financial history',
            simulated_backlog=True, natural_long_idle_reproduction=False, proofs=proofs, problems=problems,
            pending=pending, result=result, routes=counts, registration_requests=0,
            network_policy=dict(use_proxy=True, proxy_fallback=True, request_retries=2),
            sessions=dict(identity.sessions.stats), connections=dict(http.native_connections.stats),
            same_cutoff_repeat_requests=0, idle_connection_retries=c.stats['idle_connection_retries'])
    finally:
        yuanhang_client.exchange_frame = original
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        redis = create_client(cfg['redis'])
        try:
            keys = [k async for k in redis.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await redis.delete(*keys)
            session.report['private_redis_cleaned'] = True
        finally:
            await redis.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mysql', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    cfg, root = load_config(), Path(__file__).resolve().parents[1]
    paths = ['src/empire/sources/yuanhang_auth.py', 'src/empire/features/yuanhang/collector.py',
             'src/empire/sources/yuanhang_client.py', 'src/empire/plugins/infra/native_connections.py',
             'scripts/probe_yuanhang_idle_recovery.py']
    test = json.loads(Path(args.test_mysql).read_text('utf8'))
    with CapacitySession(cfg['mysql'], test, root=root, subject='preview', output=args.output, input_paths=paths) as session:
        session.report['bindings'] = session.frozen_inputs
        with session.source_engine.connect() as conn:
            session.require_source(conn)
            registry = ProfileRegistry(ReadOnlyIdentitySettings(conn, cfg['redis']['namespace']), WindowsProtection())
            profiles = asyncio.run(registry.load())
        asyncio.run(collect(session, cfg, profiles))
        session.measurements_complete = True
    print('PASS one complete financial history: injected idle recovery, proxy, private archive/query, clean queue')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('FAIL idle recovery verification: ' + type(exc).__name__) from None
