"""Bounded complete-stock dividend initialization and unchanged maintenance."""
import asyncio
import copy
import sys

import source_verification as verification
from catalogue_verification import require_drained
from foundation_verification import routed
from PySide6.QtCore import QCoreApplication
from source_verification import require

from empire.features.capital_actions import dividend_history
from empire.features.capital_actions.contract import digest, unit_key


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.tdx_dividends')
    c = manager.registry.get('collector.tdx_dividends')
    q = manager.registry.get('dividends.query')
    original = dividend_history.collect_history
    expected = {}

    async def observe(*a, **kw):
        units, observed, checksum = await original(*a, **kw)
        expected.clear()
        expected.update(copy.deepcopy(units))
        return units, observed, checksum

    routes = {}
    dividend_history.collect_history = observe
    try:
        revision = await c.checkpoint_revision()
        first = await routed(lambda: c.execute(baseline_revision=revision), routes, args.proxy_only)
        require(set(expected) == {unit_key(s) for s in await q.securities()}, '证券范围缺漏')
        actual = []
        while True:
            rows = await q.list_events(limit=500, offset=len(actual))
            actual.extend(rows)
            require(len(actual) <= 100000, '正式查询超限')
            if len(rows) < 500:
                break
        actual.sort(key=lambda r: r['record_key'])
        wanted = sorted([r for rows in expected.values() for r in rows], key=lambda r: r['record_key'])
        require(actual == wanted, '来源组合与正式查询不同')
        initial_digest = digest(actual)
        require(await require_drained(manager) == 0, '初始化未清队')
        revision = await c.checkpoint_revision()
        second = await routed(lambda: c.execute(baseline_revision=revision), routes, args.proxy_only)
        require(second['network_costs']['http_attempts'] - second['network_costs']['retries'] == 1,
                '无变化分红维护应只读报告期目录（允许共享下载器有界重试）')
        require(c.stats['downloaded_report_periods'] == 0 and c.stats['assembled_securities'] == 0,
                '无变化分红重下报告期或重组证券')
        require(second['pages'] == 1 and await require_drained(manager) == 0, '无变化分红重复发布证券或未清队')
        report['results']['tdx-dividends'] = dict(pipeline_verified=True, acceptance_complete=True,
            initial=first, maintenance=second, rows=len(actual), content_digest=initial_digest,
            stocks=len(expected), routes=routes, pending_stream=0,
            reused_report_periods=c.stats['reused_report_periods'], reused_securities=c.stats['reused_securities'])
        report['scope'] = dict(unit='complete_security_history', securities=len(expected),
            limitation='选定证券完整历史，报告期完整市场响应；不证明生产全市场完成')
    finally:
        dividend_history.collect_history = original


def main():
    parser = verification.parser(__doc__)
    args = parser.parse_args()
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verification.verify(
        args, verify_scope, subject='tdx-dividend-maintenance', fixed_codes=('688110.SH', '600007.SH'), minimum_random=30))
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
