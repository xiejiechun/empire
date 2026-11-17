"""Validate one complete historical day through shared HTTP; never publish business data."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from empire.bootstrap import build_manager
from empire.core.config import default_config_path, load_config
from empire.core.redaction import Redactor
from empire.core.time import CHINA
from empire.features.graymarket.contract import START, day, digest
from empire.features.graymarket.download import GraymarketDownload
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def no_publication_capacity(**kwargs):
    # This diagnostic never calls ingest or archives. No queue capacity is owned.
    return None


async def run(args):
    stamp = day(args.date)
    if stamp < START or stamp >= datetime.now(CHINA).date().isoformat():
        raise ValueError("来源核实仅接受已结束且不早于声明起点的一个日期")
    cfg = load_config(args.config or default_config_path())
    manager = build_manager(cfg)
    counts = {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    try:
        await manager.start("infra.http")
        owner = GraymarketDownload()
        owner.http = manager.registry.get("http.fetch")
        owner.records = manager.registry.get("collection.records")
        owner.ingest = SimpleNamespace(ensure_capacity=no_publication_capacity)
        owner.stats, owner.request_retries = {}, 2
        async with owner.daily_reads([stamp]) as reads:
            async for _, read in reads:
                rows, observed = await read.resolve()
                result = dict(
                    scope="source-only; no Redis business publication or SQL archive",
                    date=stamp, observed_at=observed.isoformat(), rows=len(rows),
                    unique_keys=len({r[0] for r in rows}),
                    content_sha256=digest(rows), key_sha256=digest([r[0] for r in rows]),
                    markets=dict(Counter(r[0].split(".")[1] for r in rows)),
                    requests=owner.stats["requests"], routes=counts,
                    max_daily_rows=10000, page_size=100,
                )
        result["retained_bytes_after"] = owner.http.buffer_budget.used
        if args.report:
            # Exclusive creation prevents overwriting another run's evidence.
            with Path(args.report).open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        raise RuntimeError(Redactor.from_config(cfg).text(exc, 2048)) from None
    finally:
        try:
            await manager.shutdown()
        finally:
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            ROUTE_COUNTS.reset(tokens[2])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--config")
    parser.add_argument("--report")
    asyncio.run(run(parser.parse_args()))
