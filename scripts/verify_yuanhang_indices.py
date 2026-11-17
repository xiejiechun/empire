"""Fixed 5% complete indices through native/web sources, Redis, SQL and queries."""
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
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.core.redaction import redact
from empire.features.yuanhang_indices.contract import FIELDS, digest, number
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService

SEED = 20261116
FIXED = ['1A0001', '1B0007', '1B0008', '1B0009', '1B0070',
         '399412', '399556', '399557', '899050', '980023']


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
    routes, member_proofs, price_proofs = {}, {}, {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(routes)
    try:
        await manager.start('collector.yuanhang_indices')
        catalog = manager.registry.get('collector.yuanhang_indices')
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
        await manager.start('collector.yuanhang_index_members')
        members = manager.registry.get('collector.yuanhang_index_members')
        members.selected_codes = sample
        member_fetch = members.fetch
        async def capture_members(item, *, reservation):
            deferred = await member_fetch(item, reservation=reservation)
            consume = deferred.consume
            async def capture():
                result = await consume()
                member_proofs[item['code']] = dict(available=result['available'], count=len(result['members']),
                    hash=digest([result['available'], result['members']]))
                return result
            deferred.consume = capture
            return deferred
        members.fetch = capture_members
        print(f'Collecting {len(sample)} complete web member units', flush=True)
        await members.execute(fresh=True)
        await manager.start('collector.yuanhang_index_prices')
        prices = manager.registry.get('collector.yuanhang_index_prices')
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
            price_proofs[item[0]] = dict(count=len(rows), hash=digest(rows), first=rows[0][0], last=rows[-1][0],
                plan=copy.deepcopy(prices.plans[item[0]]))
            return rows, observed
        prices.fetch = capture_price
        print(f'Collecting {len(sample)} complete native histories through {prior}', flush=True)
        await prices.execute(fresh=True)
        async def query_rows(code):
            rows, cursor = [], None
            while True:
                result = await prices.query.browse(code=code, after=cursor, limit=500)
                rows.extend([[r['trade_date'].isoformat()]+[number(r[f]) for f in FIELDS] for r in result['rows']])
                cursor = result['next']
                if cursor is None:
                    return rows
        for code, proof in price_proofs.items():
            rows = await query_rows(code)
            if len(rows) != proof['count'] or digest(rows) != proof['hash']:
                raise ValueError('完整日K正式查询与来源内容不一致：'+code)
        with session.engine.connect() as conn:
            for code, proof in member_proofs.items():
                rows = [list(r) for r in conn.execute(text('SELECT source_code,name FROM ths_index_member WHERE index_code=:c ORDER BY source_code'), dict(c=code))]
                head = conn.execute(text('SELECT * FROM ths_index_member_state WHERE index_code=:c'), dict(c=code)).mappings().one()
                if (digest([proof['available'],rows]) != proof['hash'] or head['member_hash'] != proof['hash']
                        or head['member_count'] != (len(rows) if proof['available'] else None)):
                    raise ValueError('成分实际集合或状态不一致：'+code)
        initial_proofs = copy.deepcopy(price_proofs)
        prices.query.scope = real_scope
        price_proofs.clear()
        before = dict(routes)
        print(f'Checking next trading day {through}', flush=True)
        await prices.execute(baseline_revision=await prices.checkpoint_revision())
        incremental = {}
        for code, proof in price_proofs.items():
            plan = proof['plan']
            rows = [r for r in await query_rows(code) if plan['start'] <= r[0] <= plan['through']]
            if len(rows) != proof['count'] or digest(rows) != proof['hash']:
                raise ValueError('新增日K正式查询与来源不一致：'+code)
            incremental[code] = dict(start=plan['start'], through=plan['through'], **proof)
        after = dict(routes)
        async def forbidden(*args, **kwargs):
            raise AssertionError('同日无变化或Redis断点丢失不得重下日K')
        prices.fetch = forbidden
        await prices.execute(baseline_revision=await prices.checkpoint_revision())
        redis = manager.registry.get('redis.store')
        await redis.client.delete(redis.prefix+':checkpoint:'+prices.job_key)
        await prices.execute()
        if routes != after:
            raise ValueError('无变化/断点丢失产生了多余来源请求')
        checks = await prices.query.preparation_check(dict(index_codes=sample))
        coverage = next(c for c in checks if c.criterion == 'coverage')
        if coverage.status != 'pass':
            raise ValueError('历史准备检查失败：'+coverage.measured)
        pending = await redis.client.xlen(redis.stream)
        if pending or routes.get('direct_requests',0) or routes.get('direct_fallbacks',0):
            raise ValueError('代理/归档清队验收失败')
        session.report.update(member_proofs=member_proofs, initial_price_proofs=initial_proofs,
            incremental=dict(prior=prior, through=through, proofs=incremental,
                routes={k:after.get(k,0)-before.get(k,0) for k in after}),
            repeated_source_requests=0, redis_checkpoint_loss_source_requests=0,
            pending=pending, source_quality=[dict(criterion=c.criterion,status=c.status) for c in checks])
    finally:
        records = manager.registry.optional('collection.records')
        if records:
            session.report['error_records'] = {p: await records.list_error_summaries(p, limit=100)
                for p in ('ths-yuanhang-indices','ths-yuanhang-index-members','ths-yuanhang-index-prices')}
        session.report.update(routes=routes, registration_requests=0,
            statuses={k:dict(e.plugin.stats) for k,e in manager.entries.items() if k.startswith('collector.yuanhang_index')})
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
    paths = [p.relative_to(root).as_posix() for p in (root/'src/empire/features/yuanhang_indices').glob('*.py')]
    paths += ['scripts/verify_yuanhang_indices.py', 'src/empire/sources/yuanhang_wire.py']
    with CapacitySession(cfg['mysql'], json.loads(Path(args.test_mysql).read_text('utf8')), root=root,
            subject='indices', output=args.output, input_paths=paths) as session:
        with session.source_engine.connect() as conn:
            session.require_source(conn)
            conn.exec_driver_sql('START TRANSACTION READ ONLY')
            registry = ProfileRegistry(ReadOnlyIdentitySettings(conn,cfg['redis']['namespace']), WindowsProtection())
            profiles = asyncio.run(registry.load())
            conn.rollback()
        session.report.update(bindings=session.frozen_inputs, network_policy=dict(use_proxy=True,proxy_fallback=False))
        asyncio.run(collect(session,cfg,profiles))
        session.measurements_complete = True
    print('PASS native catalogue + 5% complete member/history units; pending=0', flush=True)


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
