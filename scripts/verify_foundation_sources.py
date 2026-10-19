"""Verify finite foundation sources using the shared UUID-owned lifecycle."""
import asyncio
import sys

import source_verification as verification
from foundation_verification import verify_calendar, verify_stocks, verify_suspensions
from PySide6.QtCore import QCoreApplication


async def verify_scope(manager, selection, args, report):
    verification.require(len(args.kinds) == len(set(args.kinds)), '来源类型重复')
    for kind in args.kinds:
        if kind in ('sina', 'ths'):
            await verify_stocks(manager, kind, args.proxy_only, report)
        elif kind == 'calendar':
            await verify_calendar(manager, args.months, args.proxy_only, report)
        else:
            await verify_suspensions(manager, args.start, args.end, args.proxy_only, report)


def parser():
    value = verification.parser(__doc__)
    value.set_defaults(random_count=0, timeout=600)
    value.add_argument('--kinds', nargs='+', choices=('sina', 'ths', 'calendar', 'suspensions'),
                       default=['sina', 'ths', 'calendar', 'suspensions'])
    value.add_argument('--months', nargs='+', default=['1990-12', '2026-10', '2027-12'])
    value.add_argument('--start', default='2004-12-27')
    value.add_argument('--end', default='2004-12-31')
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else
        verification.verify(args, verify_scope, subject='foundation', require_proxy=True,
            non_stock_scope=dict(unit='complete_directories_and_finite_calendar_dates',
                reason='股票目录整份请求；日历与停复牌按日期请求完整响应，非逐股票采集', fixed=[])))
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
