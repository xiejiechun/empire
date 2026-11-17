"""One fixed complete instrument (ceil(12*5%)) through the formal pipeline."""
import asyncio
import hashlib
import re
from datetime import UTC, datetime

import source_verification as verification
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.features.fx.contract import DATASET, SYMBOLS, digest
from empire.features.fx.source import annual, candle, current_candle, realtime, recent
from empire.features.fx.verification import agrees, reconcile
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

CODE = 'USDCNH'


def prepare(selection, args, report):
    selection.update(instrument_pool=list(SYMBOLS), selected_instruments=[CODE], seed=None,
        sample_ratio=1 / 12, policy='Fixed offshore RMB boundary; ceil(12*0.05)=1 complete instrument, all advertised years; no replacement on failure')


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.ths_fx_daily')
    await manager.start('collector.ths_fx_live')
    daily, live, query = [manager.registry.get(k) for k in ('collector.ths_fx_daily', 'collector.ths_fx_live', 'fx.daily.query')]
    daily.selected_codes = live.selected_codes = [CODE]
    daily.request_retries = 4  # Bounded acceptance-only retry, saved task policy untouched.
    http, expected, responses, routes = daily.http, {}, [], {}
    annual_bodies = {}
    original = http.request
    async def request(method, url, **kwargs):
        verification.require(re.fullmatch(r'https://d\.10jqka\.com\.cn/(?:v4/(?:line/wh_USDCNH/01/(?:last|\d{4})|realhead/wh_USDCNH/last)|v6/line/wh_USDCNH/01/today)\.js', url) is not None, '请求超出固定品种')
        observed = datetime.now(UTC)
        response = await original(method, url, **kwargs)
        try:
            unit = url.rsplit('/', 1)[1].split('.')[0]
            if '/realhead/' in url:
                expected['live'] = realtime(response.content.decode(), CODE, observed)
                count = 1
            elif unit == 'today':
                expected['current'] = current_candle(response.content.decode(), CODE, observed)
                count = 1
            elif unit == 'last':
                expected['snapshot'] = recent(response.content.decode(), CODE, observed)
                count = len(expected['snapshot']['rows'])
            else:
                annual_bodies[int(unit)] = response.content.decode()
                rows = candle(annual_bodies[int(unit)], CODE, int(unit))[1]
                count = len(rows)
            responses.append(dict(unit='live' if '/realhead/' in url else unit, count=count,
                bytes=len(response.content), sha256=hashlib.sha256(response.content).hexdigest()))
            return response
        except BaseException:
            response.close()
            raise
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(routes)
    http.request = request
    try:
        result = await daily.execute(fresh=True, baseline_revision=await daily.checkpoint_revision())
        verification.require(result['phase'] == 'complete', '日线未完成')
        snapshot = expected['snapshot']
        if not agrees(snapshot, expected['current'], datetime.now(UTC)):
            years = {int(expected['current'][0][:4]), int(snapshot['end'][:4])}
            snapshot, _ = reconcile(snapshot,
                {year: candle(annual_bodies[year], CODE, year)[1] for year in years}, datetime.now(UTC), expected['current'])
        verification.require(agrees(snapshot, expected['current'], datetime.now(UTC)), '历史与原生当日日线核验不一致')
        expected['snapshot'] = snapshot
        rows = 0
        for year in sorted(expected['snapshot']['years']):
            expected[int(year)] = annual(annual_bodies[int(year)], CODE, int(year), snapshot)
            values = await query.history(CODE, int(year))
            verification.require(values == expected[int(year)], '来源与正式查询全年日期或数值不一致')
            rows += len(values)
        store = manager.registry.get('redis.store')
        verification.require(await store.client.xlen(store.stream) == 0, '日线消息未清队')
        # Realtime is observed under a global SQL prohibition, after startup.
        def reject(*args):
            raise AssertionError('Realtime accessed MySQL')
        event.listen(Engine, 'before_cursor_execute', reject)
        try:
            await live.execute()
            latest = await manager.registry.get('fx.latest.query').browse(CODE)
            verification.require(len(latest['rows']) == 1, '最新值缺失')
            value = latest['rows'][0]
            verification.require(all(value[k] == expected['live'][k] for k in ('symbol', 'latest', 'open', 'high', 'low', 'previous_close', 'source_time', 'source_update_time')), '实时内容与来源不符')
            verification.require(await store.client.xlen(store.stream) == 0, '实时发布了归档消息')
        finally:
            event.remove(Engine, 'before_cursor_execute', reject)
        report['results'][DATASET] = dict(pipeline_verified=True, acceptance_complete=True,
            strict_proxy_verified=verification.strict_proxy(routes, len(expected['snapshot']['years']) + 3),
            routes=routes, responses=responses, business_rows=rows, years=expected['snapshot']['years'],
            full_history_digest=digest({y: expected[int(y)] for y in expected['snapshot']['years']}),
            pending=0, realtime_zero_sql=True, untested_instruments=[s for s in SYMBOLS if s != CODE])
    finally:
        report['source_attempts'] = dict(routes=routes, responses=responses,
            request_retries=daily.request_retries)
        http.request = original
        annual_bodies.clear()
        for variable, token in zip((USE_PROXY, PROXY_FALLBACK, ROUTE_COUNTS), tokens):
            variable.reset(token)


if __name__ == '__main__':
    args = verification.parser(__doc__).parse_args()
    action = verification.recover(args) if args.cleanup_only else verification.verify(args, verify_scope,
        subject='fx', require_proxy=True, non_stock_scope=dict(unit='complete instrument',
            reason='Twelve fixed forex-page instruments, source-year completeness', fixed=[CODE]), prepare_scope=prepare)
    passed = asyncio.run(action)
    print('PASS' if passed else 'FAIL')
    raise SystemExit(0 if passed else 1)
