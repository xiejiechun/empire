"""Fixed random30 native-proxy acceptance in an owned private MySQL/Redis scope."""
import argparse
import asyncio
import copy
import json
from datetime import date
from pathlib import Path

from capacity_session import CapacitySession
from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.contracts.request_retry import MAX_REQUEST_RETRIES
from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.core.redaction import redact
from empire.features.yuanhang.availability import DeferredSecurity
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.sources.yuanhang_coverage import financial_proofs, year_proof
from empire.sources.yuanhang_payload import (
    PRICE_FIELDS,
    daily_years,
    digest,
    financial_payload,
    number,
)
from empire.sources.yuanhang_profiles import KEY, ProfileRegistry
from empire.sources.yuanhang_range_payload import daily_ranges
from empire.sources.yuanhang_service import IdentityService


class ReadOnlyIdentitySettings:
    def __init__(self, conn, namespace):
        self.conn, self.namespace = conn, namespace

    async def load(self, kind):
        raw = self.conn.execute(text('SELECT payload FROM app_setting WHERE namespace=:ns '
            'AND kind=:kind AND setting_key=:key'), dict(ns=self.namespace, kind=kind, key=KEY)).scalar_one_or_none()
        return {KEY: json.loads(raw) if isinstance(raw, str) else raw} if raw is not None else {}


async def collect(session, cfg, profiles, sample, request_retries=2):
    source_namespace = cfg['redis']['namespace']
    cfg = copy.deepcopy(cfg)
    cfg['mysql'] = session.settings
    cfg['redis']['namespace'] = 'empire:test:' + session.run_id
    initialize_database(cfg['mysql'])
    with session.source_engine.connect() as source:
        session.require_source(source)
        stocks = source.execute(text('SELECT unified_code,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings().all()
        calendar = source.execute(text('SELECT trade_date,is_trade,updated_at FROM trade_calendar '
            "WHERE trade_date>='1990-12-19' ORDER BY trade_date LIMIT 54901")).mappings().all()
        sites = source.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns "
            "AND kind='site' AND setting_key IN ('ths','eastmoney')"),
            dict(ns=source_namespace)).mappings().all()
    with session.engine.begin() as conn:
        conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:unified_code,:name)'), [dict(r) for r in stocks])
        conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:trade_date,:is_trade,:updated_at)'),
                     [dict(r) for r in calendar])
        for row in sites:
            conn.execute(text("INSERT INTO app_setting(namespace,kind,setting_key,payload) "
                "VALUES(:ns,'site',:key,:payload)"),
                dict(ns=cfg['redis']['namespace'], key=row['setting_key'], payload=row['payload']))
    manager = build_manager(cfg)
    # The verification scope reuses decrypted production profiles read-only in memory.
    # Its identity plugin never watches, builds profiles or applies for new accounts.
    class Registry:
        async def load(self):
            return profiles
    identity_plugin = manager.entries['source.yuanhang_identity'].plugin
    identity = None
    async def start(context):
        nonlocal identity
        identity = IdentityService(Registry(), context.get('proxy.pool'), context.get('http.fetch'),
                                   context.get('collection.records'))
        return {'yuanhang.identity': identity}
    async def stop():
        if identity:
            await identity.close()
    identity_plugin.start, identity_plugin.stop = start, stop
    counts, expected, outcomes = {}, {}, {}
    price_fetch = None
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    try:
        for financial in (False, True):
            capability = 'collector.yuanhang_financial' if financial else 'collector.yuanhang_prices'
            await manager.start(capability)
            c = manager.registry.get(capability)
            c.request_retries = request_retries
            c.selected_codes = sample
            fetch = c.fetch
            if not financial:
                price_fetch = fetch
                original_scope = c.query.collection_scope
                _, current_through = await original_scope(sample)
                prior_through = max(r['trade_date'].isoformat() for r in calendar
                                    if r['is_trade'] and r['trade_date'].isoformat() < current_through)
                async def initial_scope(selected=None):
                    codes, _ = await original_scope(selected)
                    return codes, prior_through
                c.query.collection_scope = initial_scope
            async def capture(unit, *, reservation, fetch=fetch, financial=financial):
                snap = await fetch(unit, reservation=reservation)
                code = unit[0]
                if isinstance(snap, DeferredSecurity):
                    proofs = {'deferred': snap.evidence()}
                elif financial:
                    proofs = financial_proofs(financial_payload(snap, code=code))
                else:
                    proofs = {p['year']: year_proof(p) for p in daily_years(snap, code=code,
                                                                          through=date.fromisoformat(unit[2]))}
                expected[(financial, code)] = proofs
                return snap
            c.fetch = capture
            try:
                result = await c.execute()
            finally:
                if not financial:
                    c.query.collection_scope = original_scope
            outcomes[capability] = result
        query, redis = (manager.registry.get(k) for k in ('yuanhang.history.query', 'redis.store'))
        results = []
        for code in sample:
            for financial in (False, True):
                proof = expected[(financial, code)]
                problems = (['prelisting_history_conflict'] if await query.has_history(code, financial=financial) else []) if 'deferred' in proof else await query.audit_source_proofs(code, proof, financial=financial)
                result = dict(code=code, dataset='financial' if financial else 'prices', proofs=proof, problems=problems)
                if not financial and 'deferred' not in proof:
                    result['source_quality'] = await query.price_quality(code)
                elif financial and 'deferred' not in proof:
                    result['source_quality'] = await query.financial_quality(code)
                results.append(result)
        # The initial whole-history proof must pass before exercising the real
        # next-day window. Additional development reads are not runtime double reads.
        if any(r['problems'] for r in results):
            raise ValueError('Initial source-to-SQL proof mismatch')
        prices = manager.registry.get('collector.yuanhang_prices')
        increments = {}
        async def capture_increment(unit, *, reservation=None):
            snap = await price_fetch(unit, reservation=reservation)
            if isinstance(snap, DeferredSecurity):
                increments[unit[0]] = dict(deferred=snap.evidence())
            else:
                plan = prices.plans[unit[0]]
                payloads = (daily_ranges(snap, code=unit[0], start=date.fromisoformat(plan['start']),
                                         through=date.fromisoformat(unit[2])) if plan['mode'] == 'range' else
                            daily_years(snap, code=unit[0], through=date.fromisoformat(unit[2])))
                increments[unit[0]] = dict(mode=plan['mode'], payloads=payloads)
            return snap
        prices.fetch = capture_increment
        before = dict(counts)
        incremental_result = await prices.execute(baseline_revision=await prices.checkpoint_revision())
        incremental_stats = dict(prices.stats)
        incremental_proofs = []
        for code, item in increments.items():
            if 'deferred' in item:
                incremental_proofs.append(dict(code=code, deferred=item['deferred']))
                continue
            for payload in item['payloads']:
                start = payload.get('start', f"{payload['year']}-01-01")
                end = min(payload['through'], f"{payload['year']}-12-31")
                raw = await query.prices(code, start=start, end=end, limit=500)
                rows = [[r['trade_date'].isoformat()] + [number(r[k], nullable=k in ('volume_shares','amount_yuan'))
                        for k in PRICE_FIELDS] for r in raw['rows']]
                if raw['next'] is not None or rows != payload['rows']:
                    raise ValueError('Incremental source-to-formal-query content mismatch: ' + code)
                incremental_proofs.append(dict(code=code, start=start, end=end,
                    count=len(rows), content_hash=digest(rows), mode=item['mode']))
        after_increment = dict(counts)
        # Deferred prelisting securities must still be rechecked; prove zero
        # business requests on the actually listed sample using SQL-restored plans.
        listed = [code for code in sample if 'deferred' not in increments.get(code, {})]
        prices.selected_codes = listed
        plans = await query.daily_plans(redis.prefix, listed, current_through)
        if any(p['mode'] != 'skip' for p in plans.values()):
            raise ValueError('SQL recovery unnecessarily requests already verified daily ranges')
        def no_request(*args, **kwargs):
            raise AssertionError('Same-cutoff completed maintenance must not request history')
        prices.fetch = no_request
        repeated = await prices.execute(baseline_revision=await prices.checkpoint_revision())
        if counts != after_increment:
            raise ValueError('Repeated completed cutoff made unexpected network requests')
        session.report['incremental'] = dict(initial_through=prior_through, through=current_through,
            source_proofs=incremental_proofs, stats=incremental_stats, pages=incremental_result['pages'],
            routes={k: counts.get(k,0)-before.get(k,0) for k in counts},
            repeat_pages=repeated['pages'], repeat_source_requests=0, sql_restored_skip_count=len(plans))
        pending = await redis.client.xlen(redis.stream)
        if pending or any(r['problems'] for r in results) or counts.get('direct_requests', 0) or counts.get('direct_fallbacks', 0):
            raise ValueError('Native proxy/source/SQL verification did not pass')
        session.report.update(routes=counts, pending=pending, outcomes=outcomes, securities=results,
                              registration_requests=0, source_security_count=len(sample))
    finally:
        records = manager.registry.optional('collection.records')
        if records:
            session.report['error_records'] = {project: await records.list_error_summaries(project, limit=100)
                for project in ('ths-yuanhang-prices', 'ths-yuanhang-financial')}
        session.report.update(routes=counts, completed_source_units=len(expected), outcomes=outcomes,
            collector_status={k: dict(e.plugin.stats) for k, e in manager.entries.items()
                              if k in ('collector.yuanhang_prices', 'collector.yuanhang_financial')},
            registration_requests=0)
        http = manager.registry.optional('http.fetch')
        if http:
            session.report['native_connections'] = dict(http.native_connections.stats)
        if identity:
            session.report['shared_sessions'] = dict(identity.sessions.stats)
        try:
            await manager.shutdown()
        finally:
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            ROUTE_COUNTS.reset(tokens[2])
            redis = create_client(cfg['redis'])
            try:
                keys = [k async for k in redis.scan_iter(match=cfg['redis']['namespace'] + ':*')]
                if keys:
                    assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                    await redis.delete(*keys)
            finally:
                await redis.aclose()


def run(args):
    root, cfg = Path(__file__).resolve().parents[1], load_config(args.config)
    test = json.loads(Path(args.test_mysql).read_text('utf-8'))
    source_evidence = json.loads((root/'docs/evidence/ths-yuanhang-history-source-2026-10-24.json').read_text('utf-8'))
    sample = sorted(set(source_evidence['sample'] + source_evidence['fixed'] + args.fixed))
    paths = [p.relative_to(root).as_posix() for p in (root/'src/empire/features/yuanhang').glob('*.py')]
    paths += ['src/empire/sources/' + name + '.py' for name in (
        'yuanhang_client', 'yuanhang_history', 'yuanhang_payload', 'yuanhang_coverage', 'yuanhang_wire',
        'yuanhang_ranges', 'yuanhang_range_payload', 'listing_scope',
        'yuanhang_service', 'yuanhang_sessions', 'yuanhang_auth')]
    paths += ['src/empire/plugins/infra/' + name + '.py' for name in
              ('http', 'stream_exchange', 'native_connections')]
    paths += ['scripts/verify_yuanhang_history.py']
    with CapacitySession(cfg['mysql'], test, root=root, subject='preview', output=args.output, input_paths=paths) as session:
        with session.source_engine.connect() as conn:
            session.require_source(conn)
            registry = ProfileRegistry(ReadOnlyIdentitySettings(conn, cfg['redis']['namespace']), WindowsProtection())
            profiles = asyncio.run(registry.load())
        session.report.update(bindings=session.frozen_inputs, sample=sample, dataset_subject='yuanhang',
            additional_fixed=args.fixed,
            sample_seed=source_evidence.get('seed'), sampling_evidence='docs/evidence/ths-yuanhang-history-source-2026-10-24.json',
            network_policy=dict(use_proxy=True, proxy_fallback=True, request_retries=args.request_retries))
        asyncio.run(collect(session, cfg, profiles, sample, args.request_retries))
        session.measurements_complete = True
    print('PASS fixed random30 plus known native counterexamples → Redis → MySQL formal query; pending=0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--test-mysql', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--request-retries', type=int, choices=range(MAX_REQUEST_RETRIES+1), default=2)
    parser.add_argument('--fixed', action='append', default=[], help='已知失败证券额外固定加入，不替换随机30股')
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
