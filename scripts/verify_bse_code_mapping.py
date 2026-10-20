"""One complete official BSE table through shared proxy and owned archive storage."""
import asyncio
import hashlib
import sys
from datetime import UTC, datetime

import source_verification as verification
from measure_bse_capacity import make_event, publish, read_rows
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.features.security_aliases import dataset
from empire.features.security_aliases.contract import URL
from empire.features.security_aliases.source import parse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def verify_scope(manager, selection, args, report):
    await manager.start('infra.http')
    await manager.start('pipeline.ingest')
    http = manager.registry.get('http.fetch')
    counts = {}
    result = report['results']['official_table'] = dict(pipeline_verified=False, routes=counts)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts)
    observed = datetime.now(UTC)
    try:
        response = await http.request('GET', URL, allowed_domains=('bse.cn',), project_id=dataset.PROJECT,
            policy=http.response_policy('generic'), max_retries=2, max_redirects=0,
            headers={'Accept': 'text/html,*/*', 'Origin': 'https://www.bse.cn',
                     'Referer': 'https://www.bse.cn/', 'User-Agent': 'Mozilla/5.0'})
        try:
            rows = parse(response.content)
            result.update(source_url=URL, response_sha256=hashlib.sha256(response.content).hexdigest(),
                          response_bytes=len(response.content), source_count=len(rows))
        finally:
            response.close()
    finally:
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
    envelope = make_event(rows).model_copy(update={'observed_at': observed})
    normalized = dataset.normalize(envelope)
    require(normalized['rows'] == rows and normalized['row_count'] == len(rows), '来源到规范集合内容不同')
    await publish(manager, envelope)
    stored = await manager.registry.get('mysql.store').read(read_rows, manager.registry.get('mysql.store'))
    require(stored == rows, '来源到正式有界SQL完整集合或内容不同')
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '本轮待归档或隔离非空')
    require(any(row['legacy_code'] == '836149' and row['unified_code'] == '920149.BJ' for row in rows),
            '已知官方换码固定反例缺失')
    result.update(pipeline_verified=True, acceptance_complete=True, strict_proxy_verified=strict_proxy(counts, 1),
        source_query_equal=True, source_set_digest=verification.digest(rows), sql_set_digest=verification.digest(stored),
        sql_count=len(stored), pending=pending, fixed_example=next(row for row in rows if row['legacy_code'] == '836149'),
        limitation='一次完整官方换码表；不是当前北交所名单，不证明来源未公布关系或生产全历史')


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verification.verify(
        args, verify_scope, subject='bse_code_mapping', require_proxy=True,
        non_stock_scope=dict(unit='complete_official_mapping_table',
            reason='官方一次完整表响应；不按股票请求，不以当前名单过滤历史换码关系', fixed=['836149 -> 920149.BJ'])))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
