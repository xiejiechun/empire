"""Bounded real-source financial verification using the shared private lifecycle."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.contracts.security import split_unified_code, unified_code
from empire.features.financial_statements.contract import KINDS, digest, validate_rows
from empire.features.financial_statements.quality import quality_issues
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

# Historical failures (date, long matrix, transport), plus financial-sector
# structures and the original end-to-end sample. These supplement random 30.
FIXED_CODES = ('920000.BJ', '000001.SZ', '600018.SH', '600104.SH', '600502.SH',
               '600644.SH', '601139.SH', '601398.SH', '601318.SH', '600030.SH')


def row_summary(kind: str, stock: dict, rows: list[dict]) -> dict:
    unit = stock['market'] + ':' + stock['code']
    validate_rows(kind, unit, rows)
    require(all(row['name'] == stock['name'] for row in rows), '来源名称与冻结样本不同')
    return dict(unit=unit, unified_code=unified_code(stock['market'], stock['code']), count=len(rows),
                dates=[row['report_date'] for row in rows], digest=digest(rows),
                reports=[dict(date=row['report_date'], digest=digest(row), fields=len(row['fields']),
                              quality=quality_issues(kind, row)) for row in rows])


def observe_fetch(collector, selected: list[dict], summaries: dict):
    """Return an instance wrapper; keep original response/reservation ownership."""
    original = collector.fetch
    wanted = {row['unified_code'] for row in selected}

    def remember(stock, result):
        rows, observed, url = result
        summary = row_summary(collector.kind, stock, rows)
        key = summary['unified_code']
        require(key in wanted, '来源返回样本外证券')
        require(key not in summaries, '同一证券重复消费；拒绝用覆盖掩盖重复')
        summaries[key] = {**summary, 'observed_at': observed.isoformat(), 'source_url': url}
        return result

    async def fetch(stock, *, reservation=None, defer=False):
        result = await original(stock, reservation=reservation, defer=defer)
        if not defer:
            return remember(stock, result)
        require(isinstance(result, DeferredResponse), '正式 fetch 未返回 DeferredResponse')
        consume = result.consume

        async def observed_consume():
            return remember(stock, await consume())

        result.consume = observed_consume
        return result

    return fetch


def observe_publish(collector, summaries: dict, published: dict):
    original = collector.publish

    async def publish(state, cursor, unit, rows, manifest, observed, url):
        require(unit not in published, '正式入队单元重复')
        if unit == 'manifest':
            require(not rows and manifest == expected_manifest(summaries), '入队manifest与来源不同')
        else:
            expected = next((row for row in summaries.values() if row['unit'] == unit), None)
            require(expected is not None and expected['digest'] == digest(rows)
                    and expected['count'] == len(rows), '入队集合或内容与来源不同')
        result = await original(state, cursor, unit, rows, manifest, observed, url)
        require(result['revision'] == state['revision'] + 1, '正式Redis入队断点版本异常')
        published[unit] = dict(revision=result['revision'], cursor=dict(result['cursor']),
                               rows_digest=digest(rows), count=len(rows), manifest=manifest)
        return result

    return publish


def expected_manifest(summaries: dict) -> dict:
    ordered = sorted(summaries.values(), key=lambda row: row['unit'])
    keys, count, rolling = [], 0, digest([])
    for row in ordered:
        keys.append(row['unit'])
        count += row['count']
        rolling = digest([rolling, row['unit'], row['digest'], row['count']])
    return dict(units=len(keys), count=count, scope_hash=digest(keys), digest=rolling)


async def verify_kind(manager, kind: str, selected: list[dict], proxy_only: bool, result: dict) -> None:
    await manager.start('collector.ths_' + kind)
    collector = manager.entries['collector.ths_' + kind].plugin
    query = manager.entries['data.' + kind].plugin
    require(collector.source == query.source == 'ths', '财报正式来源必须保持 ths')
    require(collector.project_id == query.project_id == 'ths-' + kind
            and collector.job_key == 'ths-' + kind + '-v1', '正式项目身份发生变化')
    checkpoint = await collector.ingest.checkpoint(collector.job_key)
    require(not checkpoint['cursor'] and checkpoint['revision'] == 0, '测试 namespace 已有断点')
    summaries, counts, published = {}, {}, {}
    result.update(source='ths', project_id=collector.project_id, dataset=kind + '.statement',
                  routes=counts, source_units=summaries, published_units=published, pipeline_verified=False)
    original, original_publish = collector.fetch, collector.publish
    collector.fetch = observe_fetch(collector, selected, summaries)
    collector.publish = observe_publish(collector, summaries, published)
    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(not proxy_only), ROUTE_COUNTS.set(counts))
    try:
        cursor = await collector.execute(fresh=False, baseline_revision=checkpoint['revision'])
    finally:
        collector.fetch = original
        collector.publish = original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
    require(cursor.get('phase') == 'complete', '采集未完成')
    require(set(summaries) == {row['unified_code'] for row in selected}, '来源证券集合与冻结样本不一致')
    require(set(published) == {row['unit'] for row in summaries.values()} | {'manifest'},
            '正式Redis入队集合不一致')
    comparisons = []
    for stock in selected:
        security = stock['unified_code']
        market, code = split_unified_code(security)
        rows = await query.statement_history(security)
        actual = row_summary(kind, dict(market=market, code=code, name=stock['name']), rows)
        expected = {key: summaries[security][key] for key in actual}
        require(actual == expected, '正式查询报告期集合或内容不一致：' + security)
        comparisons.append(dict(query_equal=True, **actual))
    complete, fresh, count, actual, observed, findings = await query.mysql.read(query._audit)
    manifest = expected_manifest(summaries)
    require(complete and findings.get('integrity_ok') and actual == manifest,
            '正式 audit 未确认来源集合、SQL 内容及整轮 manifest 一致')

    def sql_state():
        with query.mysql.read_engine.connect() as conn:
            return read_state(conn, query.namespace, query.project_id, 'ths')

    state = await query.mysql.read(sql_state)
    require(all(state.get('manifest', {}).get(key) == value for key, value in manifest.items()),
            'SQL collection_state manifest 不一致')
    require(set(state.get('units', {})) == {row['unit'] for row in summaries.values()},
            'SQL collection_state 证券集合不一致')
    for summary in summaries.values():
        proof = state['units'][summary['unit']]
        require(proof.get('dates') == summary['dates'] and proof.get('digest') == summary['digest'],
                'SQL 单证券证明与来源不一致')
    require(collector.source == query.source == 'ths', '运行期间来源身份发生变化')
    pending = await collector.ingest.redis.client.xlen(collector.ingest.redis.stream)
    archive = manager.registry.get('archive.worker')
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '待归档非零或统一归档器处于隔离')
    preparation = [asdict(check) for check in await query.preparation_check()]
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(selected)),
                  cursor=cursor, pending=pending, query_units=comparisons, sql_manifest=state['manifest'],
                  expected_manifest=manifest, audit=dict(complete=complete, fresh=fresh, count=count,
                  observed=observed.isoformat() if observed else None), preparation=preparation,
                  data_usability=dict(analysis_usable=all(check['status'] == 'pass' for check in preparation
                                      if check['blocking']), findings=findings))


async def verify_scope(manager, selection, args, report):
    require(bool(args.kinds) and set(args.kinds) <= set(KINDS)
            and len(set(args.kinds)) == len(args.kinds), '财报 kinds 无效或重复')
    report['kinds'] = args.kinds
    for kind in args.kinds:
        result = report['results'][kind] = {}
        await verify_kind(manager, kind, selection['selected'], args.proxy_only, result)


def parser():
    value = verification.parser(__doc__)
    value.add_argument('--kinds', nargs='+', choices=list(KINDS), default=list(KINDS))
    return value


def main(argv=None):
    options = parser().parse_args(argv)
    _qt_app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(options) if options.cleanup_only else
                         verification.verify(options, verify_scope, subject='financial_statements',
                             fixed_codes=FIXED_CODES, minimum_random=30, require_proxy=True))
    print(('CLEANUP COMPLETE' if options.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
