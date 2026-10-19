"""Synthetic seven-kind SQL guard smoke; makes zero real source requests."""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import source_verification as verification
from kaipanla_verification import verify_kind
from PySide6.QtCore import QCoreApplication

from empire.features.kaipanla.contract import PRODUCTS
from tests.prefetch_source import prefetch_http
from tests.test_kaipanla_intraday import listing
from tests.test_kaipanla_products import source


async def scope(manager, selection, args, report):
    for kind in PRODUCTS:
        await manager.start('collector.kaipanla_' + kind)
        collector = manager.registry.get('collector.kaipanla_' + kind)
        original = collector.http
        async def request(method, url, **options):
            if 'eastmoney.com' in url:
                return httpx.Response(200, json=listing())
            assert options['attempt_options']()['data']['StockID'] == '000001'
            return httpx.Response(200, json=source(kind))
        collector.http = prefetch_http(request=request)
        result = report['results'][kind] = dict(synthetic=True, source_requests=0)
        try:
            await verify_kind(manager, kind, selection['selected'], [date(2021, 1, 4)], [], False, result)
            verification.require(result['source_units'] == result['query_units'],
                                 '合成SQL冒烟的来源与正式查询摘要域不同')
        finally:
            collector.http = original
    report.update(synthetic=True, source_requests=0)


def main(argv=None):
    args = verification.parser(__doc__).parse_args(argv)
    args.random_count, args.seed, args.codes, args.proxy_only = 0, None, ['000001.SZ'], False
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else
        verification.verify(args, scope, subject='synthetic_kaipanla_sql_smoke'))
    print('SQL SMOKE PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
