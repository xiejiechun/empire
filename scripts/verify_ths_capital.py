"""Scoped real verification on the shared proxy-first downloader; no saved HTML."""
import argparse
import asyncio
import hashlib
import json
import random
import secrets
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.ths_capital import PROJECT, TABLES, digest
from empire.core.config import load_config
from empire.core.preparation_release import source_digest
from empire.core.redaction import redact
from empire.plugins.collectors.ths_capital_source import parse
from empire.plugins.collectors.ths_session import ThsSession
from empire.plugins.datasets.ths_capital import read_window
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


def select_sample(pool, codes, count, seed):
    if type(count) is not int or not 0 <= count <= 100 or len(codes) != len(set(codes)) or any(
            len(c) != 6 or not c.isascii() or not c.isdigit() for c in codes):
        raise ValueError('抽样数量须为0～100且固定证券为不重复六位代码')
    by_code = {r['code']: r for r in pool}
    if len(by_code) != len(pool) or not set(codes) <= by_code.keys():
        raise ValueError('当前股票池证券不唯一或固定回归证券缺失')
    eligible = sorted(set(by_code) - set(codes))
    if len(eligible) < count or not count + len(codes) or count + len(codes) > 100:
        raise ValueError('抽样池不足或所选总数不在1～100范围')
    sampled = sorted(random.Random(seed).sample(eligible, count))
    selected = sorted([by_code[c] for c in [*sampled, *codes]], key=lambda r: r['unified_code'])
    return selected, dict(seed=seed, algorithm='random.Random.sample without replacement on sorted codes',
        pool_count=len(pool), pool_digest=digest(sorted(r['unified_code'] for r in pool)),
        random_codes=sampled, required_codes=sorted(codes))


async def run(args):
    if args.apply and args.random_count < 30:
        raise ValueError('实采验收必须至少随机30只股票；固定回归不抵扣随机样本')
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    manager, counts, expected = build_manager(cfg), {}, {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(False)
    ROUTE_COUNTS.set(counts)
    report = dict(checked_at=datetime.now(UTC).isoformat(), applied=args.apply, policy=dict(use_proxy=True,
        proxy_fallback=False), network=counts, securities={}, errors={}, passed=False,
        source_sha256=source_digest(Path(__file__).resolve().parents[1]))
    def summary(value):
        return dict(counts={t: len(value['rows'][t]) for t in TABLES}, digest=digest(value),
                    availability=value['availability'], normalized_bytes=len(json.dumps(value, ensure_ascii=False).encode()))
    try:
        await manager.start('infra.http')
        mysql = manager.registry.get('mysql.store')
        codes = args.codes.split(',') if args.codes else []
        def securities():
            with mysql.read_engine.connect() as conn:
                result = [dict(r) for r in conn.execute(text('SELECT unified_code,LEFT(unified_code,6) AS code,name '
                    'FROM stock ORDER BY unified_code LIMIT 15001')).mappings()]
                if not result or len(result) > 15000:
                    raise ValueError('股票池为空或超限')
                return result
        pool = await mysql.read(securities)
        stocks, report['sampling'] = select_sample(pool, codes, args.random_count,
            args.seed if args.seed is not None else secrets.randbits(64))
        codes = [r['code'] for r in stocks]
        report['selected_codes'] = codes
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf8')
        session = ThsSession()
        if not args.apply:
            http = manager.registry.get('http.fetch')
            for stock in stocks:
                url = f"https://basic.10jqka.com.cn/{stock['code']}/capital.html"
                response = await http.request('GET', url, headers=session.headers(url), allowed_domains=('10jqka.com.cn',),
                    project_id='ths-capital-discovery', max_retries=2, policy=http.response_policy('generic'))
                try:
                    value = parse(response.content, stock, datetime.now().date())
                    report['securities'][stock['unified_code']] = {**summary(value),
                        'response_bytes': len(response.content), 'response_sha256': hashlib.sha256(response.content).hexdigest()}
                except (ValueError, TypeError, KeyError) as exc:
                    report['errors'][stock['unified_code']] = redact(exc, cfg)
                finally:
                    response.close()
        else:
            await manager.start('collector.ths_capital')
            collector, query = manager.registry.get('collector.ths_capital'), manager.registry.get('ths_capital.query')
            collector.session = session
            async def selected():
                return stocks
            collector.query.securities = selected
            original = collector.fetch
            async def capture(stock, **kwargs):
                response = await original(stock, **kwargs)
                consume = response.consume
                async def wrapped():
                    value, observed, url = await consume()
                    expected[stock['unified_code']] = value
                    return value, observed, url
                response.consume = wrapped
                return response
            collector.fetch = capture
            cursor = await asyncio.wait_for(collector.execute(fresh=True, baseline_revision=await collector.checkpoint_revision()), args.timeout)
            if len(expected) != len(stocks):
                raise ValueError('本轮未取得全部证券来源集合')
            for unit, value in expected.items():
                def read(unit=unit):
                    with mysql.read_engine.begin() as conn:
                        return read_window(conn, unit)
                if await mysql.read(read) != value['rows']:
                    raise ValueError('来源→Redis→SQL→正式查询集合或内容不符：' + unit)
                report['securities'][unit] = {**summary(value), 'source_to_sql_equal': True}
            report['audit'] = await mysql.read(query.audit, PreparationScope(codes=tuple(codes)))
            report['cursor'] = cursor
            store = manager.registry.get('redis.store')
            report['pending'] = await store.client.xlen(store.stream)
            if not report['audit']['complete'] or report['pending']:
                raise ValueError('资本运作正式审计未通过或待归档非零')
            settings = SettingsStore(mysql, store.prefix)
            saved = await settings.load('task')
            if PROJECT not in saved:
                definition = manager.entries['collection.control'].plugin.definitions[PROJECT]
                policy = definition.default_schedule.policy(dict(enabled=definition.default_enabled,
                    use_proxy=True, proxy_fallback=True, request_retries=2))
                await settings.save('task', PROJECT, policy)
                report['saved_default'] = policy
            else:
                report['preserved_saved_policy'] = True
        if report['errors']:
            raise ValueError('来源验证失败：' + str(report['errors']))
        if counts.get('proxy_requests', 0) < len(stocks) or counts.get('direct_requests', 0) or counts.get('fallback_requests', 0):
            raise ValueError('代理实采证据不足或存在直连请求')
        report['passed'] = bool(args.apply)
        print('PASS archive verification' if args.apply else 'PROBE parsed only', len(report['securities']), 'securities', counts)
    except Exception as exc:
        report['failure'] = redact(exc, cfg)
        raise
    finally:
        try:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        finally:
            try:
                await manager.shutdown()
            finally:
                if lock:
                    lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--codes', default='', help='额外固定回归证券，不占随机样本名额')
    parser.add_argument('--random-count', type=int, default=30)
    parser.add_argument('--seed', type=int, help='失败重验使用报告中的原种子和固定证券')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--report', default='build/ths-capital-verification.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
