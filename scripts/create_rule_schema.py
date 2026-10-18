"""Explicit additive rule maintenance; app startup never creates these tables."""
import argparse
import asyncio
from copy import copy
from pathlib import Path

from create_name_change_schema import run


async def maintain(args):
    for table in ('trading_rule_citation', 'trading_rule_value'):
        scoped = copy(args)
        if args.report:
            path = Path(args.report)
            scoped.report = str(path.with_name(path.stem + '-' + table + path.suffix))
        await run(scoped, table=table)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    asyncio.run(maintain(parser.parse_args()))
