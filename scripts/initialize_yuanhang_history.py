"""Explicit full-pool native initialization and source-to-formal-query audit.

Run only with Empire closed. Each invocation starts a full verification round;
it never deletes existing history or changes saved task/network policies.
"""
import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.request_retry import MAX_REQUEST_RETRIES
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang.availability import DeferredSecurity
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.sources.yuanhang_coverage import financial_proofs, year_proof
from empire.sources.yuanhang_payload import CONTRACT, daily_years, digest, financial_payload
from scripts.release_identity import input_inventory
from scripts.yuanhang_initialization_audit import load_resume, require_owned_pending, seed


def source_proofs(snapshot, code, through, financial):
    if isinstance(snapshot, DeferredSecurity):
        if snapshot.code != code or snapshot.through != through:
            raise ValueError('初始化上市前范围证据身份或截止日不一致')
        return {'deferred': snapshot.evidence()}
    if financial:
        return financial_proofs(financial_payload(snapshot, code=code))
    return {p['year']: year_proof(p) for p in daily_years(snapshot, code=code, through=date.fromisoformat(through))}


def summarize(code, expected):
    nonempty = [p for p in expected.values() if p['row_count']]
    return dict(code=code, units=len(expected), rows=sum(p['row_count'] for p in expected.values()),
        first=min((p['first_date'] for p in nonempty), default=None),
        last=max((p['last_date'] for p in nonempty), default=None),
        source_proof_hash=digest(expected))


async def audit(query, codes, expected, *, financial):
    if set(expected) != set(codes):
        raise ValueError('初始化来源证券集合不完整，不能只按数量验收')
    result = []
    for code in codes:
        proof = expected.pop(code)
        if 'deferred' in proof:
            result.append(dict(units=0, rows=0, **proof['deferred'],
                problems=['prelisting_history_conflict'] if await query.has_history(code, financial=financial) else []))
            continue
        problems = await query.audit_source_proofs(code, proof, financial=financial)
        if not financial and set(await query.year_heads(code)) != set(proof):
            problems.append('annual_key_set_mismatch')
        item = {**summarize(code, proof), 'problems': problems}
        if not financial:
            item['source_quality'] = await query.price_quality(code)
        else:
            item['source_quality'] = await query.financial_quality(code)
        result.append(item)
    return result


async def initialize(cfg, report, *, apply, resume=None, request_retries=2):
    manager = build_manager(cfg)
    counts = {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    try:
        await manager.start('data.yuanhang')
        query = manager.registry.get('yuanhang.history.query')
        codes, through = await query.collection_scope()
        from sqlalchemy import text
        target = await query._read(lambda conn: dict(conn.execute(
            text('SELECT DATABASE() AS database_name,@@server_uuid AS server_uuid')).mappings().one()))
        target['namespace'] = cfg['redis']['namespace']
        saved = seed(resume, target=target, codes=codes, through=through)
        report.update(stock_count=len(codes), stocks=codes, scope_hash=digest(codes), through=through,
                      network_policy=dict(use_proxy=True, proxy_fallback=True, request_retries=request_retries), datasets={},
                      target=target, audit_contract=CONTRACT, audit_sources={})
        if not apply:
            return
        await manager.start('infra.redis')
        redis = manager.registry.get('redis.store')
        if await redis.client.xlen(redis.stream):
            if not saved:
                raise RuntimeError('初始化前存在其他待归档消息，请先通过正式归档处理')
            await require_owned_pending(redis, saved)
        # Both datasets use precisely the same frozen pool and closed-day cutoff.
        async def frozen_scope(selected=None):
            return codes, through
        query.collection_scope = frozen_scope
        for financial in (False, True):
            ident = 'collector.yuanhang_financial' if financial else 'collector.yuanhang_prices'
            await manager.start(ident)
            collector = manager.registry.get(ident)
            collector.request_retries = request_retries
            prior = saved.get(collector.project_id)
            if prior and await collector.ingest.checkpoint(collector.job_key) != prior['checkpoint']:
                raise ValueError('初始化审计与现有采集断点不同，不能复用旧来源证明')
            expected = dict(prior['proofs']) if prior else {}
            received = set()
            fetch = collector.fetch
            async def capture(unit, *, reservation, fetch=fetch, financial=financial):
                try:
                    snapshot = await fetch(unit, reservation=reservation)
                    expected[unit[0]] = source_proofs(snapshot, unit[0], through, financial)
                    received.add(unit[0])
                except ValueError as exc:
                    raise ValueError(unit[0] + ': ' + str(exc)) from None
                return snapshot
            collector.fetch = capture
            async def progress():
                while True:
                    await asyncio.sleep(15)
                    print(json.dumps(dict(project=collector.project_id, **collector.stats,
                        pending=await redis.client.xlen(redis.stream)), ensure_ascii=False), flush=True)
            ticker = asyncio.create_task(progress())
            try:
                baseline = 0 if prior else await collector.checkpoint_revision()
                result = await collector.execute(fresh=not prior, baseline_revision=baseline)
                report['audit_sources'][collector.project_id] = dict(
                    checkpoint=await collector.ingest.checkpoint(collector.job_key), proofs=dict(expected))
                checks = await audit(query, codes, expected, financial=financial)
                pending = await redis.client.xlen(redis.stream)
                report['datasets'][collector.project_id] = dict(outcome=result, securities=checks, pending=pending)
                if pending or any(item['problems'] for item in checks):
                    raise ValueError('初始化来源/SQL集合或内容核验未通过，保留具体缺口')
            finally:
                if expected and collector.project_id not in report['audit_sources']:
                    checkpoint = await collector.ingest.checkpoint(collector.job_key)
                    n = checkpoint['cursor'].get('next_index', 0)
                    report['audit_sources'][collector.project_id] = dict(checkpoint=checkpoint,
                        proofs={code: expected[code] for code in codes[:n] if code in expected})
                report.setdefault('source_units_received', {})[collector.project_id] = len(received)
                collector.fetch = fetch
                ticker.cancel()
                await asyncio.gather(ticker, return_exceptions=True)
            print(json.dumps(dict(project=collector.project_id, audited=len(checks),
                                  rows=sum(c['rows'] for c in checks), pending=pending)), flush=True)
        if counts.get('direct_requests', 0) or counts.get('direct_fallbacks', 0):
            raise ValueError('初始化存在非代理请求，不能通过代理验收')
        report['initialization_complete'] = True
    finally:
        report['routes'] = counts
        report['collector_status'] = {k: dict(e.plugin.stats) for k, e in manager.entries.items()
            if k in ('collector.yuanhang_prices', 'collector.yuanhang_financial')}
        try:
            await manager.shutdown()
        finally:
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            ROUTE_COUNTS.reset(tokens[2])


def run(args):
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(args.config)
    output = Path(args.report)
    if output.exists():
        raise FileExistsError('初始化证据须使用新路径，不能覆盖已有报告')
    report = dict(started_at=datetime.now(UTC).isoformat(), initialization_complete=False, applied=args.apply)
    lock = acquire_instance_lock() if args.apply else None
    inputs = input_inventory(root)
    try:
        resume = load_resume(args.resume_report, inputs=inputs)
        asyncio.run(initialize(cfg, report, apply=args.apply, resume=resume, request_retries=args.request_retries))
        if input_inventory(root) != inputs:
            raise RuntimeError('初始化期间源码改变，结果不能作为同一版本验收')
        report.update(input_identity_verified=True, bindings=inputs)
    except BaseException as exc:
        report.update(initialization_complete=False, error=redact(exc, cfg))
        raise
    finally:
        report.update(bindings=inputs, input_identity_verified=input_inventory(root) == inputs)
        report['finished_at'] = datetime.now(UTC).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n', 'utf-8')
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--request-retries', type=int, choices=range(MAX_REQUEST_RETRIES+1), default=2)
    parser.add_argument('--resume-report', help='显式复用同源码、同池、同截止日失败轮的来源摘要；仍使用原Redis断点')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
