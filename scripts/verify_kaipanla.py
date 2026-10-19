"""Finite seven-product proofs through the shared UUID-owned verification lifecycle."""
import asyncio
import sys

import source_verification as verification
from kaipanla_verification import FIXED_CODES, prepare_reference, verify_scope
from PySide6.QtCore import QCoreApplication

from empire.features.kaipanla.contract import PRODUCTS


def parser():
    value = verification.parser(__doc__)
    value.set_defaults(timeout=1800)
    value.add_argument('--kinds', nargs='+', choices=list(PRODUCTS), default=list(PRODUCTS))
    value.add_argument('--days', nargs='+', default=['2026-09-30'])
    value.add_argument('--fixed-days', nargs='+', default=['2026-09-28', '2026-09-29', '2026-09-30'])
    return value


async def verify_live(args):
    events = None
    def prepare(selection, options, report):
        nonlocal events
        events = prepare_reference(selection, options, report)
    async def scope(manager, selection, options, report):
        await verify_scope(manager, selection, options, report, events)
    return await verification.verify(args, scope, subject='kaipanla', fixed_codes=FIXED_CODES,
                                    minimum_random=30, require_proxy=True, prepare_scope=prepare)


def main(argv=None):
    args = parser().parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else
        verify_live(args))
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
