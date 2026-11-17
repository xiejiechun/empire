"""Bounded THS optimization verification using the established private lifecycle."""
import asyncio
import sys

import source_verification as verification
import verify_listings
import verify_ths_capital
import verify_ths_holders
import verify_ths_statements
from catalogue_verification import require_drained, verify_catalogue
from PySide6.QtCore import QCoreApplication
from source_verification import require

from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY


async def securities(manager, selection, args, report):
    args.kinds = ['income', 'balance', 'cashflow']
    for verify in (verify_ths_statements.verify_scope, verify_ths_capital.verify_scope,
                   verify_ths_holders.verify_scope, verify_listings.verify_scope):
        await verify(manager, selection, args, report)
    # Same-period second round must not issue source requests for confirmed
    # finance/capital units. It still uses the official completion boundary.
    for feature in ('income', 'balance', 'cashflow', 'capital'):
        collector = manager.registry.get('collector.ths_' + feature)
        cursor = await collector.execute(baseline_revision=await collector.checkpoint_revision())
        require(cursor['network_costs']['http_attempts'] == 0, '同周期重复下载：' + feature)
        require(cursor['phase'] == 'complete', '维护未完成')
        report['results']['maintenance_' + feature] = dict(pipeline_verified=True,
            acceptance_complete=True, network_costs=cursor['network_costs'],
            reused_units=collector.stats['reused_units'], pending=await require_drained(manager))


async def industries(manager, selection, args, report):
    await verify_catalogue(manager, 'industries', args.proxy_only, report)


def main():
    parser = verification.parser(__doc__)
    parser.add_argument('--scope', choices=('securities', 'industries'), required=True)
    args = parser.parse_args()
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    token, fallback = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only)
    try:
        if args.scope == 'industries':
            args.random_count = 0
            passed = asyncio.run(verification.verify(args, industries, subject='ths-industry-optimization',
                non_stock_scope=dict(unit='complete_industry_snapshot', reason='完整行业集合不可截断', fixed=[])))
        else:
            passed = asyncio.run(verification.verify(args, securities, subject='ths-securities-optimization',
                fixed_codes=verify_ths_statements.FIXED_CODES, minimum_random=30))
    finally:
        PROXY_FALLBACK.reset(fallback)
        USE_PROXY.reset(token)
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
