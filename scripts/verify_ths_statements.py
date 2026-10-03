"""Bounded live three-statement acceptance through the shared pipeline in isolated storage."""
import argparse
import asyncio
import copy
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.plugins.datasets.financial_quality import quality_issues
from empire.plugins.datasets.financial_statements import KINDS, digest
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.plugins.infra.settings import SettingsStore

EXAMPLES = {'920000', '920009', '920748', '601139', '600000', '601398', '601318',
            '601628', '600030', '000001', '000002', '300750', '688981', '600519',
            '600036', '601166', '601688', '601211', '601601', '000166'}


def select_stocks(stocks):
    selected = {s['code']: s for s in stocks if s['code'] in EXAMPLES}
    for market in ('BJ', 'SH', 'SZ'):
        group = [s for s in stocks if s['market'] == market]
        if group:
            for n in range(13):
                stock = group[(len(group) - 1) * n // 12]
                selected[stock['code']] = stock
    return sorted(selected.values(), key=lambda s: (s['market'], s['code']))


async def verify(config, output):
    cfg = copy.deepcopy(load_config(config))
    production_namespace = cfg['redis']['namespace']
    token = uuid4().hex
    cfg['redis']['namespace'] = 'empire:test:ths:' + token
    source = 'test-' + token
    manager = build_manager(cfg)
    result = dict(checked_at=datetime.now(CHINA).isoformat(), results={}, isolated=True)
    mysql = store = None
    try:
        await manager.start('data.income')
        query = manager.entries['data.income'].plugin
        mysql = query.mysql
        policies = await SettingsStore(mysql, production_namespace).load('task')
        selected = select_stocks(await query.securities())
        result['securities'] = [s['market'] + ':' + s['code'] for s in selected]
        for kind in KINDS:
            query = manager.entries['data.' + kind].plugin
            collector = manager.entries['collector.ths_' + kind].plugin
            query.source = collector.source = source
            query._securities = lambda conn: selected
            await manager.start('collector.ths_' + kind)
            store = manager.registry.get('redis.store')
            policy = policies.get('ths-' + kind, {})
            proxy = USE_PROXY.set(policy.get('use_proxy', True))
            fallback = PROXY_FALLBACK.set(policy.get('proxy_fallback', True))
            collector.request_retries = policy.get('request_retries', 2)
            expected = {}
            fetch = collector.fetch

            async def capture(stock):
                rows, observed, url = await fetch(stock)
                expected[stock['code']] = digest(rows)
                return rows, observed, url

            collector.fetch = capture
            try:
                completed = await collector.execute()
                issues = Counter()
                findings, units = [], []
                for stock in selected:
                    rows = await query.list_statements(stock['code'], 500)
                    assert digest(rows) == expected[stock['code']], 'Source/query contents differ'
                    for row in rows:
                        for issue in quality_issues(kind, row):
                            issues[issue['criterion']] += 1
                            findings.append(dict(code=stock['code'], date=row['report_date'], **issue))
                    units.append(dict(code=stock['code'], dates=[r['report_date'] for r in rows],
                                      digest=digest(rows)))
                result['results'][kind] = dict(status=completed['phase'], reports=completed['collected'],
                    source_query_equal=True, units=units, quality_counts=dict(issues), findings=findings,
                    preparation=[vars(c) for c in await query.preparation_check()])
            except Exception as exc:
                result['results'][kind] = dict(status='failed', error=collector.records.sanitize_text(exc),
                                              fetched=len(expected), current=collector.stats.get('current_security'))
            finally:
                USE_PROXY.reset(proxy)
                PROXY_FALLBACK.reset(fallback)
            print(json.dumps({kind: {k: v for k, v in result['results'][kind].items()
                                    if k not in ('units', 'findings', 'preparation')}}, ensure_ascii=True), flush=True)
        result['pending'] = await store.client.xlen(store.stream)
        result['passed'] = result['pending'] == 0 and all(
            r['status'] == 'complete' for r in result['results'].values())
    finally:
        await manager.stop('pipeline.archive', cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    for _, _, table in KINDS.values():
                        conn.execute(text(f'DELETE FROM {table} WHERE source=:source'), {'source': source})
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:test:ths:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()
        result['isolated_records_removed'] = True
        Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=None)
    parser.add_argument('--output', required=True, help='Summary and normalized identity evidence; no raw responses')
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(verify(args.config, args.output)) else 1)
