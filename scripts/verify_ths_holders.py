"""Scoped proxy-first real verification; apply uses the single-instance archive."""
import argparse
import asyncio
import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.collector import CollectionSourceGap
from empire.contracts.holders import KINDS, digest, report_key
from empire.contracts.holders import project as holder_project
from empire.contracts.preparation_scope import PreparationScope
from empire.core.config import load_config
from empire.core.preparation_release import source_digest
from empire.core.redaction import redact
from empire.plugins.collectors.ths_holders_source import parse
from empire.plugins.collectors.ths_session import ThsSession
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


def summary(rows):
    return dict(reports=len(rows), members=sum(len(r['members']) for r in rows), digest=digest(rows),
                report_keys=[report_key(r) for r in rows],
                max_report_bytes=max((len(json.dumps(r, ensure_ascii=False).encode()) for r in rows), default=0))


async def run(args):
    if args.rebuild_proofs and not args.apply:
        raise ValueError('重建证明必须使用正式入队归档验证')
    if not 0 <= args.random_count <= 15000:
        raise ValueError('随机数量或来源缺口验证范围无效')
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    manager, counts = build_manager(cfg), {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(not args.proxy_only)
    ROUTE_COUNTS.set(counts)
    report = dict(checked_at=datetime.now(UTC).isoformat(), applied=args.apply, projects={},
                  policy=dict(use_proxy=True, proxy_fallback=not args.proxy_only), network=counts,
                  source_sha256=source_digest(Path.cwd()))
    try:
        await manager.start('infra.http')
        mysql = manager.registry.get('mysql.store')
        def securities():
            with mysql.read_engine.connect() as conn:
                pool = [dict(r) for r in conn.execute(text('SELECT unified_code,LEFT(unified_code,6) AS code,'
                    'RIGHT(unified_code,2) AS market,name FROM stock ORDER BY unified_code')).mappings()]
                sampled = random.Random(args.seed).sample(pool, args.random_count)
                report['sampling'] = dict(seed=args.seed, pool_count=len(pool),
                    pool_digest=digest([s['unified_code'] for s in pool]),
                    random_securities=[s['unified_code'] for s in sampled], fixed_codes=args.codes.split(','))
                if args.all_stocks:
                    return pool
                result = []
                for code in filter(None, args.codes.split(',')):
                    if len(code) != 6 or not code.isascii() or not code.isdigit():
                        raise ValueError('证券参数无效')
                    values = list(conn.execute(text('SELECT unified_code,LEFT(unified_code,6) AS code,'
                        'RIGHT(unified_code,2) AS market,name FROM stock WHERE unified_code LIKE :code'), {'code': code + '.%'}).mappings())
                    if len(values) != 1:
                        raise ValueError('当前股票池没有唯一证券：' + code)
                    result.append(dict(values[0]))
                return sorted({s['unified_code']: s for s in result + sampled}.values(), key=lambda s: s['unified_code'])
        stocks = await mysql.read(securities)
        report['selected_securities'] = [s['unified_code'] for s in stocks]
        # Freeze the exact sample before any source request; failures cannot be replaced.
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf8')
        http, session = manager.registry.get('http.fetch'), ThsSession()
        if not args.apply:
            for stock in stocks:
                url = f"https://basic.10jqka.com.cn/{stock['code']}/holder.html"
                response = await http.request('GET', url, headers=session.headers(url), allowed_domains=('10jqka.com.cn',),
                    project_id='ths-holders-discovery', max_retries=2, policy=http.response_policy('generic'))
                try:
                    for kind in KINDS:
                        try:
                            rows = parse(response.content, kind, stock)
                        except ValueError as exc:
                            raise ValueError(stock['unified_code'] + ' / ' + kind + ': ' + str(exc)) from exc
                        p = report['projects'].setdefault(kind, {})
                        p[stock['unified_code']] = dict(reports=len(rows), members=sum(len(r['members']) for r in rows),
                            periods=[r['report_date'] for r in rows], digest=digest(rows),
                            notices=sum(r['report_type'] == 'change_notice' for r in rows),
                            rank_gaps=[r['report_date'] for r in rows if [m['source_rank'] or m['seq'] for m in r['members'] if m['member_group'] == 'current'] != list(range(1,1+sum(m['member_group'] == 'current' for m in r['members'])))],
                            report_keys=[report_key(r) for r in rows],
                            response_sha256=hashlib.sha256(response.content).hexdigest(),
                            response_bytes=len(response.content), max_report_bytes=max((len(json.dumps(r, ensure_ascii=False).encode()) for r in rows), default=0))
                finally:
                    response.close()
        else:
            await manager.start('collector.ths_holders')
            c = manager.registry.get('collector.ths_holders')
            q = manager.registry.get('top_holders.query')
            if args.rebuild_proofs:
                archive = manager.registry.get('archive.worker')
                async with archive.lock:
                    await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
            c.session = session
            async def selected():
                return stocks
            c.query.securities = selected
            source_sets, source_gaps = {}, {}
            fetch = c.fetch
            async def checked_fetch(stock, *, reservation=None, defer=False):
                response = await fetch(stock, reservation=reservation, defer=defer)
                if defer:
                    consume = response.consume
                    async def checked_consume():
                        value = await consume()
                        source_sets[stock['unified_code']] = ({k: summary(rows) for k, rows in value[0].items()}
                                                               if args.all_stocks else value[0])
                        if value[3]:
                            source_gaps[stock['unified_code']] = value[3]
                        return value
                    response.consume = checked_consume
                return response
            c.fetch = checked_fetch
            expected_gaps = set(filter(None, args.expected_gap_codes.split(',')))
            try:
                cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), args.timeout)
            except CollectionSourceGap as exc:
                actual_gaps = {s['code'] for s in stocks if s['unified_code'] not in source_sets or
                               s['unified_code'] in source_gaps}
                if not expected_gaps or actual_gaps != expected_gaps:
                    raise
                report['source_gap'] = dict(codes=sorted(actual_gaps), notice=str(exc), stats=c.health())
                cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
            if len(source_sets) != len(stocks) or {k[:6] for k in source_gaps} != expected_gaps:
                raise ValueError('本轮没有取得完整来源证券集合')
            report['source_gaps'] = source_gaps
            def proof_gaps():
                with mysql.read_engine.connect() as conn:
                    state = read_state(conn, cfg['redis']['namespace'], 'ths-holders', 'ths')
                    return {k: state['units'][k].get('source_gaps', []) for k in source_gaps}
            if await mysql.read(proof_gaps) != source_gaps:
                raise ValueError('来源缺口与正式SQL证明不一致')
            report['cursor'] = cursor
            for kind in KINDS:
                q = manager.registry.get(kind + '.query')
                if not args.all_stocks:
                    for security, sections in source_sets.items():
                        for row in sections[kind]:
                            if await q.detail(report_key(row)) != row:
                                raise ValueError('来源→归档→正式查询正文不一致')
                audit = await mysql.read(q.audit, PreparationScope(codes=tuple(s['code'] for s in stocks
                    if kind != 'bond_holders' or s['code'] not in expected_gaps)))
                if not audit['complete']:
                    raise ValueError('正式窗口集合审计失败')
                sources = {k: v[kind] if args.all_stocks else summary(v[kind]) for k, v in source_sets.items()}
                if any(audit['digests'].get(k) != v['digest'] for k, v in sources.items()
                       if kind != 'bond_holders' or k[:6] not in expected_gaps):
                    raise ValueError('来源→正式SQL审计集合及正文摘要不一致')
                if expected_gaps and kind == 'bond_holders':
                    partial = await mysql.read(q.audit, PreparationScope(codes=tuple(sorted(expected_gaps))))
                    if partial['complete'] or partial['missing'] != len(expected_gaps) or any(
                            partial['digests'].get(k) != v['digest'] for k, v in sources.items() if k[:6] in expected_gaps):
                        raise ValueError('未识别债券未保留缺口或有效报告证明不一致')
                    report['partial_bond_audit'] = partial
                report['projects'][kind] = dict(audit=audit, rebuilt_proofs=args.rebuild_proofs,
                    source=sources)
            store = manager.registry.get('redis.store')
            async def drained():
                # The selected batch has already confirmed. An older valid
                # backlog can still be draining through the same worker.
                while await store.client.xlen(store.stream):
                    worker = manager.registry.get('archive.worker')
                    if worker.blocked or worker.blocked_projects:
                        raise ValueError('归档项目隔离，保留待处理消息')
                    worker.request_flush()
                    await asyncio.sleep(1)
            await asyncio.wait_for(drained(), args.timeout)
            report['pending_stream'] = await store.client.xlen(store.stream)
            if report['pending_stream']:
                raise ValueError('归档队列仍有残留')
            if args.proxy_only and (counts.get('direct_requests', 0) or counts.get('fallback_requests', 0) or not counts.get('proxy_requests', 0)):
                raise ValueError('代理验收未全部通过代理')
            # Persist only absent task defaults; never start the shared scheduler
            # or overwrite an existing user's network/schedule choice.
            settings = SettingsStore(mysql, store.prefix)
            saved = await settings.load('task')
            definitions = manager.entries['collection.control'].plugin.definitions
            report['task_defaults'] = {}
            for ident in (holder_project('top_holders'),):
                definition = definitions[ident]
                if ident not in saved:
                    default = dict(enabled=definition.default_enabled, mode='manual',
                        interval_seconds=definition.interval_seconds, daily_time='18:00', request_retries=2)
                    policy = definition.default_schedule.policy(default)
                    await settings.save('task', ident, policy)
                else:
                    policy = saved[ident]
                report['task_defaults'][ident] = dict(policy=policy, preserved=ident in saved)
        report['bindings'] = {str(p).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path('src/empire/contracts/holders.py'), *Path('src/empire/plugins').glob('**/*holders*.py')]}
        if report['source_sha256'] != source_digest(Path.cwd()):
            raise ValueError('实采期间源码发生变化，不能绑定当前发布验证')
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        print('PASS holder source/SQL verification', len(stocks), 'securities;', counts)
    finally:
        await manager.shutdown()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--codes', default='601139,000001,601318,600519,300750')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--proxy-only', action='store_true', help='禁用直连回退，用于随机30股代理验收')
    parser.add_argument('--random-count', type=int, default=0)
    parser.add_argument('--seed', type=int, default=20261017)
    parser.add_argument('--all-stocks', action='store_true')
    parser.add_argument('--expected-gap-codes', default='', help='明确登记的来源身份缺口；不计成功实采')
    parser.add_argument('--rebuild-proofs', action='store_true', help='持有归档锁失效三项来源摘要，重新请求并冷归档确认本范围')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--report', default='docs/evidence/ths-holders-source-2026-10-13.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
