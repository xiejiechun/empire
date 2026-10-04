"""Proxy-only one-day source storage experiment; delete all captured bodies afterward."""
import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from time import monotonic

from kaipanla_measure_support import (
    INTERFACES,
    UNCONFIRMED,
    Capture,
    atomic_report,
    decode_body,
    validate,
)

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.collectors.kaipanla_source import URL, request_options
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

ROOT = Path(__file__).resolve().parents[1]


async def measure(args):
    cfg = load_config(args.config)
    capture = Capture(ROOT / 'build' / 'kaipanla-measure-data')
    cfg['http']['download_directory'] = str(capture.incoming)
    manager = build_manager(cfg)
    started = monotonic()
    results = []
    report = {'started_at': datetime.now(CHINA).isoformat(), 'status': 'preparing',
              'source': 'kaipanla', 'requested_scope': 'all current listed stocks / latest ended trading day',
              'interfaces': list(INTERFACES), 'unconfirmed_complete_scope': UNCONFIRMED,
              'proxy_only': True, 'business_archive_modified': False,
              'storage_format': 'per-security lossless framed decoded bodies / gzip level 6; source percent/zlib codec removed',
              'not_measured': ['MySQL rows/indexes', 'directory/MFT overhead', 'backup capacity'],
              'capture_validation': 'identity/date, widths, ordered full minute keys, source Count/total; no deduplication',
              'stocks': results}
    output = Path(args.report).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('报告须位于项目目录')
    counts = {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(False)
    ROUTE_COUNTS.set(counts)
    try:
        await manager.start('infra.http')
        await manager.start('data.kaipanla_trend')
        query = manager.registry.get('kaipanla_trend.query')
        stocks, days = await query.plan()
        if args.symbols:
            selected = set(args.symbols.split(','))
            stocks = [s for s in stocks if s['unified_code'] in selected]
            if {s['unified_code'] for s in stocks} != selected:
                raise ValueError('抽样证券不在当前完整股票名单中')
        day = date.fromisoformat(args.day) if args.day else days[-1]
        if day not in days:
            raise ValueError('所选日期不是正式日历中的已结束交易日')
        pool = manager.registry.get('proxy.pool')
        await pool.refresh(waiting=True)
        exits = pool.healthy_count()
        if exits < 1:
            raise RuntimeError('没有健康代理出口；测量不允许直连回退')
        if args.limit:
            stocks = stocks[:args.limit]
        http = manager.registry.get('http.fetch')
        workers = min(args.workers, exits, http.global_limit)
        report.update(status='collecting', run_id=capture.run_id, trade_date=day.isoformat(),
                      planned_stocks=len(stocks), healthy_exit_count_at_start=exits, workers=workers,
                      scope_sha256=hashlib.sha256(json.dumps(
                          [s['unified_code'] for s in stocks], separators=(',', ':')).encode()).hexdigest(),
                      site_policy=[s for s in await http.settings() if s['name'] == 'kaipanla'])
        atomic_report(output, report)
        queue = asyncio.Queue()
        for stock in stocks:
            queue.put_nowait(stock)

        async def worker():
            while not queue.empty():
                stock = queue.get_nowait()
                item = {'unified_code': stock['unified_code'], 'interfaces': {}, 'all_known_valid': True}
                writer = capture.open(stock['unified_code'])
                try:
                    for action in INTERFACES:
                        def options():
                            value = request_options(stock['code'], day, 'trend')
                            value['data']['a'] = action
                            if action == 'StockTrendInfo':
                                value['data'].update(c='HisSuperFuPan', Date=day.isoformat(),
                                                     start='0', stop='0', isAll='1')
                            elif action == 'GetStockChouMa_New':
                                value['data'].update(Day=day.strftime('%Y%m%d'), Type='1')
                            return value
                        try:
                            async with asyncio.timeout(args.request_timeout):
                                response = await http.request('POST', URL, attempt_options=options,
                                    max_redirects=0, allowed_domains=('longhuvip.com',),
                                    project_id='kaipanla-storage-measure',
                                    policy=http.file_policy(filename=stock['unified_code'] + '-' + action + '.bin'),
                                    max_retries=2)
                            try:
                                artifact = response.artifact
                                path = Path(artifact['path']) if artifact else None
                                source_size = path.stat().st_size if path else len(response.content)
                                if source_size > 64 * 1024 * 1024:
                                    raise ValueError('source_body_processing_limit')
                                reserve = 4 * source_size + 256 * 1024
                                if action == 'StockTrendInfo':
                                    reserve += 3 * 64 * 1024 * 1024
                                lease = await http.buffer_budget.reserve(reserve)
                                try:
                                    raw = path.read_bytes() if path else response.content
                                    body = decode_body(raw)
                                    info = {'body_bytes': len(body), 'source_encoded_bytes': len(raw),
                                            'http_status': response.status_code,
                                            'sha256': hashlib.sha256(body).hexdigest()}
                                    try:
                                        info.update(validate(body, action, stock['code'], day))
                                        info['valid'] = True
                                    except (ValueError, TypeError, KeyError) as exc:
                                        info.update(valid=False, error=redact(exc, cfg)[:240])
                                        item['all_known_valid'] = False
                                    writer.write(action, body)
                                    item['interfaces'][action] = info
                                finally:
                                    raw = body = None
                                    lease.release()
                            finally:
                                response.close()
                                if response.artifact:
                                    owned = Path(response.artifact['path']).resolve()
                                    if owned.parent != capture.incoming.resolve():
                                        raise RuntimeError('unexpected_capture_download_path')
                                    owned.unlink()
                        except Exception as exc:
                            item['interfaces'][action] = {'valid': False, 'error': redact(exc, cfg)[:240]}
                            item['all_known_valid'] = False
                finally:
                    if len(item['interfaces']) != len(INTERFACES):
                        item['all_known_valid'] = False
                    item['files'] = writer.close()
                    results.append(item)
                    queue.task_done()

        tasks = [asyncio.create_task(worker()) for _ in range(workers)]
        try:
            while any(not task.done() for task in tasks):
                done = len(results)
                report.update(completed_stocks=done, elapsed_seconds=round(monotonic() - started, 1),
                              route_counts=dict(counts), valid_known_stocks=sum(s['all_known_valid'] for s in results))
                atomic_report(output, {k: v for k, v in report.items() if k != 'stocks'})
                print(json.dumps({k: report[k] for k in ('trade_date', 'planned_stocks', 'completed_stocks',
                    'valid_known_stocks', 'elapsed_seconds', 'route_counts')}, ensure_ascii=False), flush=True)
                await asyncio.wait(tasks, timeout=20, return_when=asyncio.ALL_COMPLETED)
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        report.update(status='measured', completed_stocks=len(results), storage=capture.measure())
    except BaseException as exc:
        report.update(status='interrupted' if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else 'failed',
                      error=redact(exc, cfg)[:500])
        if capture:
            report['storage'] = capture.measure()
        raise
    finally:
        try:
            await manager.shutdown()
        finally:
            if capture:
                report['cleanup'] = capture.cleanup()
        errors = Counter()
        by_api = {}
        for action in INTERFACES:
            values = [s['interfaces'].get(action, {}) for s in results]
            by_api[action] = {'attempted_stocks': sum(bool(v) for v in values),
                'valid_stocks': sum(bool(v.get('valid')) for v in values),
                'returned_body_bytes': sum(v.get('body_bytes', 0) for v in values),
                'valid_body_bytes': sum(v.get('body_bytes', 0) for v in values if v.get('valid')),
                'source_encoded_bytes': sum(v.get('source_encoded_bytes', 0) for v in values),
                'valid_rows': sum(v.get('rows', 0) for v in values if v.get('valid'))}
            errors.update(v['error'] for v in values if v.get('error'))
        report.update(finished_at=datetime.now(CHINA).isoformat(), elapsed_seconds=round(monotonic() - started, 1),
                      route_counts=counts, by_interface=by_api, error_counts=dict(errors),
                      valid_known_stocks=sum(s['all_known_valid'] for s in results),
                      known_scope_complete=(len(results) == report.get('planned_stocks') and
                                            all(s['all_known_valid'] for s in results)),
                      requested_full_scope_complete=False)
        atomic_report(output, report)
        print(json.dumps({'status': report['status'], 'report': str(output), 'storage': report.get('storage'),
                          'cleanup': report.get('cleanup'), 'route_counts': counts}, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--day', help='默认正式日历最近已结束交易日')
    parser.add_argument('--limit', type=int, default=0, help='开发抽样；0为全部当前股票')
    parser.add_argument('--symbols', help='开发分层抽样，例如000001.SZ,600519.SH,300981.SZ')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--request-timeout', type=int, default=120)
    parser.add_argument('--report', default=str(ROOT / 'build' / 'kaipanla-day-measurement.json'))
    args = parser.parse_args()
    if args.limit < 0 or not 1 <= args.workers <= 32 or not 30 <= args.request_timeout <= 600:
        parser.error('limit>=0；workers 1～32；request-timeout 30～600')
    try:
        asyncio.run(measure(args))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(type(exc).__name__ + ': ' + redact(exc, {}), file=sys.stderr)
        raise SystemExit(1) from None
