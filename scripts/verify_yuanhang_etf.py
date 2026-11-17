"""Fixed 5% complete ETF histories and full latest through shared sources, Redis, SQL and queries."""
import argparse
import asyncio
import copy
import json
import math
import random
from pathlib import Path

from capacity_session import CapacitySession
from PySide6.QtCore import QCoreApplication
from sqlalchemy import text
from verify_yuanhang_history import ReadOnlyIdentitySettings

from empire.bootstrap import build_manager
from empire.contracts.collector import CollectionSourceGap
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.core.redaction import redact
from empire.features.yuanhang_etf.contract import FIELDS, digest, number
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService

SEED = 20261116
FIXED = ['510010.SH', '510050.SH', '511010.SH', '511980.SH', '513100.SH', '518880.SH', '159653.SZ', '159915.SZ']


async def collect(session, cfg, profiles):
    original_ns = cfg['redis']['namespace']
    cfg = copy.deepcopy(cfg)
    cfg['mysql'] = session.settings
    cfg['redis']['namespace'] = 'empire:test:' + session.run_id
    initialize_database(cfg['mysql'])
    with session.source_engine.connect() as conn:
        session.require_source(conn)
        conn.exec_driver_sql('START TRANSACTION READ ONLY')
        calendar = [dict(r) for r in conn.execute(text('SELECT trade_date,is_trade,updated_at FROM trade_calendar '
            "WHERE trade_date>='1990-12-19' ORDER BY trade_date LIMIT 54901")).mappings()]
        sites = [dict(r) for r in conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns "
            "AND kind='site' AND setting_key='ths'"), dict(ns=original_ns)).mappings()]
        conn.rollback()
    with session.engine.begin() as conn:
        conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:trade_date,:is_trade,:updated_at)'), calendar)
        for row in sites:
            conn.execute(text("INSERT INTO app_setting(namespace,kind,setting_key,payload) VALUES(:ns,'site',:key,:payload)"),
                dict(ns=cfg['redis']['namespace'], key=row['setting_key'], payload=row['payload']))
    manager, identity = build_manager(cfg), None
    class Registry:
        async def load(self):
            return profiles
    async def start(context):
        nonlocal identity
        identity = IdentityService(Registry(), context.get('proxy.pool'), context.get('http.fetch'), context.get('collection.records'))
        return {'yuanhang.identity': identity}
    async def stop():
        if identity:
            await identity.close()
    plugin = manager.entries['source.yuanhang_identity'].plugin
    plugin.start, plugin.stop = start, stop
    routes, price_proofs = {}, {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(routes)
    try:
        await manager.start('collector.yuanhang_etfs')
        catalog = manager.registry.get('collector.yuanhang_etfs')
        print('Collecting complete native catalogue', flush=True)
        await catalog.execute(fresh=True)
        entries = await catalog.query.catalog()
        codes = sorted(r['code'] for r in entries)
        if not set(FIXED) <= set(codes):
            raise ValueError('固定反例不在当前目录，需明确调整样本')
        size = max(len(FIXED), math.ceil(len(codes)*0.05))
        sample = sorted(FIXED + random.Random(SEED).sample(sorted(set(codes)-set(FIXED)), size-len(FIXED)))
        session.report.update(catalog_count=len(entries), catalog_hash=digest(entries), sample=sample,
            fixed=FIXED, seed=SEED, sample_fraction=len(sample)/len(entries))
        await manager.start('collector.yuanhang_etf_prices')
        prices = manager.registry.get('collector.yuanhang_etf_prices')
        prices.selected_codes = sample
        real_scope, real_fetch = prices.query.scope, prices.fetch
        through, trades = await real_scope()
        prior = max(r['trade_date'].isoformat() for r in calendar if r['is_trade'] and r['trade_date'].isoformat() < through)
        previous_trades = sorted(r['trade_date'].isoformat() for r in calendar if r['is_trade'] and r['trade_date'].isoformat() <= prior)[-10:]
        async def initial_scope():
            return prior, previous_trades
        prices.query.scope = initial_scope
        async def capture_price(item, *, reservation):
            rows, observed = await real_fetch(item, reservation=reservation)
            if rows is None:
                price_proofs[item[0]] = dict(source_gap=True, count=0, plan=copy.deepcopy(prices.plans[item[0]]))
                return rows, observed
            price_proofs[item[0]] = dict(count=len(rows), hash=digest(rows), first=rows[0][0], last=rows[-1][0],
                plan=copy.deepcopy(prices.plans[item[0]]))
            return rows, observed
        prices.fetch = capture_price
        print(f'Collecting {len(sample)} complete native histories through {prior}', flush=True)
        try:
            await prices.execute(fresh=True)
        except CollectionSourceGap as exc:
            session.report['initial_source_gap_notice'] = str(exc)
        async def query_rows(code):
            rows, cursor = [], None
            while True:
                result = await prices.query.browse(code=code, after=cursor, limit=500)
                rows.extend([[r['trade_date'].isoformat()]+[number(r[f]) for f in FIELDS] for r in result['rows']])
                cursor = result['next']
                if cursor is None:
                    return rows
        for code, proof in price_proofs.items():
            if proof.get('source_gap'):
                if await query_rows(code):
                    raise ValueError('来源暂无证券不应写入日K：'+code)
                continue
            rows = await query_rows(code)
            if len(rows) != proof['count'] or digest(rows) != proof['hash']:
                raise ValueError('完整日K正式查询与来源内容不一致：'+code)
        initial_proofs = copy.deepcopy(price_proofs)
        prices.query.scope = real_scope
        price_proofs.clear()
        before = dict(routes)
        print(f'Checking next trading day {through}', flush=True)
        try:
            await prices.execute(baseline_revision=await prices.checkpoint_revision())
        except CollectionSourceGap as exc:
            session.report['incremental_source_gap_notice'] = str(exc)
        incremental = {}
        for code, proof in price_proofs.items():
            if proof.get('source_gap'):
                continue
            plan = proof['plan']
            rows = [r for r in await query_rows(code) if plan['start'] <= r[0] <= plan['through']]
            if len(rows) != proof['count'] or digest(rows) != proof['hash']:
                raise ValueError('新增日K正式查询与来源不一致：'+code)
            incremental[code] = dict(start=plan['start'], through=plan['through'], **proof)
        after = dict(routes)
        unavailable = {c for c,p in initial_proofs.items() if p.get('source_gap')}
        async def forbidden(item, *, reservation):
            if item[0] not in unavailable:
                raise AssertionError('同日无变化或Redis断点丢失不得重下已确认日K')
            return await real_fetch(item, reservation=reservation)
        prices.fetch = forbidden
        try:
            await prices.execute(baseline_revision=await prices.checkpoint_revision())
        except CollectionSourceGap:
            pass
        redis = manager.registry.get('redis.store')
        await redis.client.delete(redis.prefix+':checkpoint:'+prices.job_key)
        try:
            await prices.execute()
        except CollectionSourceGap:
            pass
        if not unavailable and routes != after:
            raise ValueError('无变化/断点丢失产生了多余来源请求')
        checks = await prices.query.preparation_check(dict(codes=[c[:6] for c in sample if c not in unavailable]))
        coverage = next(c for c in checks if c.criterion == 'coverage')
        if coverage.status != 'pass':
            raise ValueError('历史准备检查失败：'+coverage.measured)
        pending = await redis.client.xlen(redis.stream)
        if pending or routes.get('direct_requests',0) or routes.get('direct_fallbacks',0):
            raise ValueError('代理/归档清队验收失败')
        await manager.start('collector.yuanhang_etf_latest')
        live = manager.registry.get('collector.yuanhang_etf_latest')
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        writes = []
        def capture(conn, cursor, statement, *args):
            if statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')):
                writes.append(statement.split()[0])
        event.listen(Engine, 'before_cursor_execute', capture)
        try:
            print('Collecting complete ETF latest batches for both markets', flush=True)
            latest_result = await live.execute()
            latest_count, cursor = 0, None
            while True:
                result = await live.store.browse(after=cursor, limit=500)
                latest_count += len(result['rows'])
                cursor = result['next']
                if cursor is None:
                    break
            if writes or latest_count != len(entries):
                raise ValueError('ETF最新集合/零SQL写入验收失败')
            session.report['latest'] = dict(result=latest_result, rows=latest_count, sql_writes=len(writes))
        finally:
            event.remove(Engine,'before_cursor_execute',capture)
        session.report.update(initial_price_proofs=initial_proofs,
            incremental=dict(prior=prior, through=through, proofs=incremental,
                routes={k:after.get(k,0)-before.get(k,0) for k in after}),
            repeated_confirmed_history_requests=0, redis_checkpoint_loss_confirmed_history_requests=0,
            source_gap_codes=sorted(unavailable), source_gap_recheck_routes={k:routes.get(k,0)-after.get(k,0) for k in routes},
            pending=pending, source_quality=[dict(criterion=c.criterion,status=c.status) for c in checks])
    finally:
        records = manager.registry.optional('collection.records')
        if records:
            session.report['error_records'] = {p: await records.list_error_summaries(p, limit=100)
                for p in ('ths-yuanhang-etfs','ths-yuanhang-etf-prices','ths-yuanhang-etf-latest')}
        session.report.update(routes=routes, registration_requests=0,
            statuses={k:dict(e.plugin.stats) for k,e in manager.entries.items() if k in ('collector.yuanhang_etfs','collector.yuanhang_etf_prices','collector.yuanhang_etf_latest')})
        try:
            await manager.shutdown()
        finally:
            for variable, token in zip((USE_PROXY,PROXY_FALLBACK,ROUTE_COUNTS),tokens,strict=True):
                variable.reset(token)
            client = create_client(cfg['redis'])
            try:
                keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace']+':*')]
                if keys:
                    await client.delete(*keys)
            finally:
                await client.aclose()


def run(args):
    qt_app = QCoreApplication.instance() or QCoreApplication([])
    assert qt_app is not None
    cfg, root = load_config(args.config), Path(__file__).resolve().parents[1]
    paths = [p.relative_to(root).as_posix() for p in (root/'src/empire/features/yuanhang_etf').glob('*.py')]
    paths += ['scripts/verify_yuanhang_etf.py', 'src/empire/sources/yuanhang_wire.py', 'src/empire/sources/yuanhang_transport.py', 'src/empire/sources/yuanhang_auth.py']
    with CapacitySession(cfg['mysql'], json.loads(Path(args.test_mysql).read_text('utf8')), root=root,
            subject='indices', output=args.output, input_paths=paths) as session:
        with session.source_engine.connect() as conn:
            session.require_source(conn)
            conn.exec_driver_sql('START TRANSACTION READ ONLY')
            registry = ProfileRegistry(ReadOnlyIdentitySettings(conn,cfg['redis']['namespace']), WindowsProtection())
            profiles = asyncio.run(registry.load())
            conn.rollback()
        session.report.update(bindings=session.frozen_inputs, network_policy=dict(use_proxy=True,proxy_fallback=True))
        asyncio.run(collect(session,cfg,profiles))
        session.measurements_complete = True
    print('PASS ETF catalogue + 5% complete histories + full volatile latest; pending=0', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--test-mysql',required=True)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc,load_config(args.config))) from None
