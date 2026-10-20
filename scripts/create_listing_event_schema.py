"""Explicit additive listing-event table maintenance; no application startup DDL."""
import argparse
import asyncio

from create_name_change_schema import run

from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.listing_status.dataset import TABLE

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    try:
        asyncio.run(run(args, TABLE))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
