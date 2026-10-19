"""Complete real index/industry catalogues on UUID-owned isolated storage."""
import asyncio
import sys

import source_verification as verification
from catalogue_verification import verify_catalogue
from PySide6.QtCore import QCoreApplication


async def verify_scope(manager, selection, args, report):
    verification.require(len(args.kinds) == len(set(args.kinds)), '目录类型重复')
    for kind in args.kinds:
        await verify_catalogue(manager, kind, args.proxy_only, report)


def parser():
    value = verification.parser(__doc__)
    value.set_defaults(random_count=0, timeout=7200)
    value.add_argument('--kinds', nargs='+', choices=('indices', 'industries'), default=['indices', 'industries'])
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else
        verification.verify(args, verify_scope, subject='catalogues', require_proxy=True,
            non_stock_scope=dict(unit='complete_catalogue_and_members',
                reason='完整指数/行业目录及每项成员，不按股票采集', fixed=[])))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
