"""Strict holder-source verification in owned test storage, with honest gap evidence."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.preparation_scope import PreparationScope
from empire.core.time import CHINA
from empire.features.holders.contract import KINDS, digest, report_key, validate, validate_gaps
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

FIXED_CODES = ('300398.SZ', '601515.SH', '000912.SZ', '000430.SZ', '000065.SZ',
               '300232.SZ', '301699.SZ', '688315.SH', '002902.SZ', '301569.SZ',
               '605007.SH', '688386.SH', '920162.BJ', '601139.SH', '000001.SZ',
               '601318.SH', '600519.SH', '300750.SZ')


def row_summary(kind, security, rows, *, today=None):
    validate(kind, security, rows, today=today)
    return dict(count=len(rows), digest=digest(rows), report_keys=[report_key(row) for row in rows],
                reports=[dict(key=report_key(row), digest=digest(row), date=row['report_date'],
                    members=len(row['members']), quality_flags=row['quality_flags']) for row in rows])


def observe_fetch(collector, selected, summaries):
    """Observe consumption without replacing response/reservation/close ownership."""
    original = collector.fetch
    wanted = {row['unified_code'] for row in selected}

    def remember(stock, result):
        reports, observed, url, gaps = result
        security = stock['unified_code']
        require(security in wanted, '来源返回样本外证券')
        require(security not in summaries, '来源证券重复消费')
        require(set(reports) == set(KINDS), '来源响应缺少持有人栏目')
        validate_gaps(gaps)
        summaries[security] = dict(digest=digest(reports), gaps=[dict(row) for row in gaps],
            gaps_digest=digest(gaps), observed_at=observed.isoformat(timespec='microseconds'), url=url,
            kinds={kind: row_summary(kind, security, reports[kind], today=observed.astimezone(CHINA).date())
                   for kind in KINDS})
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


def observe_publish(collector, summaries, published):
    original = collector.publish

    async def publish(state, cursor, unit, reports, manifest, observed, url, gaps=None):
        require(unit not in published, '正式 Redis 入队单元重复')
        if unit != 'manifest':
            require(unit in summaries and digest(reports) == summaries[unit]['digest']
                    and digest(gaps or []) == summaries[unit]['gaps_digest'],
                    '正式入队内容与本轮来源规范内容不同')
        result = await original(state, cursor, unit, reports, manifest, observed, url, gaps)
        published[unit] = dict(revision=result['revision'], cursor=dict(result['cursor']),
            reports_digest=digest(reports), gaps_digest=digest(gaps or []), manifest=manifest)
        return result

    return publish


def expected_manifest(summaries):
    # The formal stock query orders full unified_code, not market/code tuples.
    securities = sorted(summaries)
    count, rolling = 0, digest([])
    kinds = {kind: dict(count=0, digest=digest([])) for kind in KINDS}
    for security in securities:
        row = summaries[security]
        unit_count = sum(part['count'] for part in row['kinds'].values())
        count += unit_count
        rolling = digest([rolling, security, row['digest'], unit_count])
        for kind, part in row['kinds'].items():
            kinds[kind]['count'] += part['count']
            kinds[kind]['digest'] = digest([kinds[kind]['digest'], security, part['digest'], part['count']])
    return dict(units=len(securities), count=count, scope_hash=digest(securities), digest=rolling,
                securities=securities, kinds=kinds)


def check_state(state, summaries, cursor, gap_outcome, published):
    require(state.get('contract_version') == 4 and set(state.get('units', {})) == set(summaries),
            'SQL 归档证明版本或证券集合不符')
    gaps = {key: row['gaps'] for key, row in summaries.items() if row['gaps']}
    for security, summary in summaries.items():
        proof = state['units'][security]
        require(proof.get('contract') == 4 and proof.get('digest') == summary['digest']
                and proof.get('source_gaps') == summary['gaps']
                and proof.get('source_gaps_digest') == summary['gaps_digest']
                and proof.get('observed_at') == summary['observed_at']
                and proof.get('count') == sum(part['count'] for part in summary['kinds'].values()),
                'SQL 证券内容/来源缺口证明不符：' + security)
        require(set(proof.get('kinds', {})) == set(KINDS), 'SQL 证券栏目集合不符')
        for kind, expected in summary['kinds'].items():
            part = proof['kinds'][kind]
            relevant = any(gap['kind'] == kind for gap in summary['gaps'])
            availability = 'source_gap' if relevant else 'available' if expected['count'] else 'not_published'
            require(part.get('contract') == 4 and part.get('availability') == availability
                    and part.get('observed_at') == summary['observed_at']
                    and all(part.get(key) == expected[key] for key in ('count', 'digest', 'report_keys')),
                    'SQL 栏目证明不符：' + security + '/' + kind)
    expected = expected_manifest(summaries)
    require(set(published) == set(summaries) | (set() if gaps else {'manifest'}), 'Redis 入队单元集合不符')
    if gaps:
        first = next(index for index, key in enumerate(sorted(summaries)) if key in gaps)
        require(gap_outcome and cursor.get('phase') != 'complete' and not state.get('manifest')
                and cursor.get('index') == first and cursor.get('source_gap') == sorted(summaries)[first],
                '来源缺口被隐藏或连续断点错误')
    else:
        require(not gap_outcome and cursor.get('phase') == 'complete', '无缺口范围未完成')
        require(all(state.get('manifest', {}).get(key) == value for key, value in expected.items()),
                'SQL 整轮 manifest 与来源集合/内容不符')
        require(published['manifest']['manifest'] == expected, 'Redis 整轮 manifest 与来源不符')
    return gaps, expected


async def query_summary(query, security):
    heads, after = [], None
    for _ in range(2):  # Source contract is at most 100 reports per issuer/kind.
        page = await query.browse(code=security, after=after, limit=100)
        heads.extend(page['rows'])
        require(len(heads) <= 100, '正式查询报告窗口超过来源上限')
        if page['next'] is None:
            break
        require(page['next'] != after, '正式查询分页游标不前进')
        after = page['next']
    else:
        raise ValueError('正式查询分页未有界结束')
    keys = [row['report_key'] for row in heads]
    require(len(keys) == len(set(keys)), '正式查询报告键重复')
    require(all(row['unified_code'] == security and row['kind'] == query.kind for row in heads),
            '正式查询证券/栏目归属错误')
    order = [(row['report_date'], row['unified_code'], row['report_key']) for row in heads]
    require(order == sorted(order, reverse=True), '正式查询分页排序错误')
    rows = []
    for head in heads:
        detail = await query.detail(head['report_key'])
        require(detail is not None and report_key(detail) == head['report_key'], '正式查询缺少报告正文')
        require(all(detail.get(key) == value for key, value in head.items()
                    if key not in {'report_key', 'member_count', 'exit_count'})
                and head['member_count'] == sum(m['member_group'] == 'current' for m in detail['members'])
                and head['exit_count'] == sum(m['member_group'] == 'exited' for m in detail['members']),
                '正式查询列表与正文内容不一致')
        rows.append(detail)
    rows.sort(key=lambda row: (row['report_date'], row['instrument_key'], row['report_type']))
    return row_summary(query.kind, security, rows)


async def verify_scope(manager, selection, args, report):
    result = report['results']['holders'] = dict(pipeline_verified=False, acceptance_complete=False)
    await manager.start('collector.ths_holders')
    collector = manager.entries['collector.ths_holders'].plugin
    queries = {kind: manager.entries['data.' + kind].plugin for kind in KINDS}
    require(collector.source == 'ths' and collector.project_id == 'ths-holders'
            and collector.job_key == 'ths-holders-v1', '正式持有人项目身份变化')
    checkpoint = await collector.ingest.checkpoint(collector.job_key)
    require(not checkpoint['cursor'] and checkpoint['revision'] == 0, '私有 namespace 已有断点')
    require(await collector.ingest.redis.client.xlen(collector.ingest.redis.stream) == 0, '私有队列非空')
    summaries, published, counts = {}, {}, {}
    result.update(source='ths', project_id='ths-holders', dataset='holders.reports', schema_version=5,
                  source_units=summaries, redis_publications=published, routes=counts)
    original_fetch, original_publish = collector.fetch, collector.publish
    collector.fetch = observe_fetch(collector, selection['selected'], summaries)
    collector.publish = observe_publish(collector, summaries, published)
    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts))
    gap_outcome = False
    try:
        try:
            cursor = await collector.execute(fresh=False, baseline_revision=0)
        except CollectionSourceGap as exc:
            gap_outcome = True
            result['source_gap_outcome'] = dict(type=type(exc).__name__, message=str(exc))
            cursor = (await collector.ingest.checkpoint(collector.job_key))['cursor']
    finally:
        collector.fetch, collector.publish = original_fetch, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
    require(set(summaries) == {row['unified_code'] for row in selection['selected']},
            '来源证券集合与冻结样本不一致，禁止换样或剔除失败股票')
    query = queries['top_holders']

    def sql_state():
        with query.mysql.read_engine.connect() as conn:
            return read_state(conn, query.namespace, 'ths-holders', 'ths')

    state = await query.mysql.read(sql_state)
    gaps, manifest = check_state(state, summaries, cursor, gap_outcome, published)
    comparisons, audits, preparation = {}, {}, {}
    for kind, query in queries.items():
        comparisons[kind] = {}
        for security, summary in summaries.items():
            actual = await query_summary(query, security)
            require(actual == summary['kinds'][kind], '正式查询集合或内容与来源不同：' + security + '/' + kind)
            comparisons[kind][security] = dict(query_equal=True, **actual)
        # Full private pool preserves market identity; the UI six-digit filter
        # is deliberately not used as a substitute for the frozen issuer set.
        audit = await query.mysql.read(query.audit, PreparationScope())
        expected_missing = sum(any(gap['kind'] == kind for gap in rows) for rows in gaps.values())
        require(audit['securities'] == len(summaries) and audit['missing'] == expected_missing
                and audit['complete'] == (expected_missing == 0)
                and set(audit['stamps']) == set(summaries)
                and audit['digests'] == {key: value['kinds'][kind]['digest'] for key, value in summaries.items()}
                and audit['reports'] == sum(row['kinds'][kind]['count'] for row in summaries.values()),
                '正式 audit 的范围、缺口或内容证明不同：' + kind)
        audits[kind] = {**audit, 'stamps': {key: stamp.isoformat() for key, stamp in audit['stamps'].items()}}
        preparation[kind] = [asdict(check) for check in await query.preparation_check()]
    pending = await collector.ingest.redis.client.xlen(collector.ingest.redis.stream)
    archive = manager.registry.get('archive.worker')
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '待归档非零或统一归档器处于隔离')
    require(collector.source == 'ths' and collector.project_id == 'ths-holders', '运行期间身份变化')
    require(collector.stats.get('status') == ('source_gap' if gaps else 'complete'), '采集完成状态与缺口不一致')
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(summaries)),
        acceptance_complete=not gaps, random_samples_complete=not (set(selection['random']) & set(gaps)),
        source_gaps=gaps, cursor=cursor, pending=pending, query_units=comparisons, audits=audits,
        expected_manifest=manifest, sql_manifest=state.get('manifest'), preparation=preparation,
        data_usability={kind: dict(analysis_usable=all(check['status'] == 'pass' for check in checks
                                                    if check['blocking'])) for kind, checks in preparation.items()})


def parser():
    return verification.parser(__doc__)


def main(argv=None):
    options = parser().parse_args(argv)
    # ThsSession evaluates the existing token script in QJSEngine. Retain the
    # non-GUI application for the full async run, as the formal collect CLI does.
    _qt_app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(options) if options.cleanup_only else verification.verify(
        options, verify_scope, subject='holders', fixed_codes=FIXED_CODES, minimum_random=30, require_proxy=True))
    print(('CLEANUP COMPLETE' if options.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
