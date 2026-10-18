"""Explicit finite real annual source → shared archive → formal SQL audit, Empire closed."""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.index_prices import PROJECT
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.collection.control import validate_policy
from empire.plugins.datasets.index_prices import sql_rows
from empire.plugins.datasets.indices import digest
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    manager = build_manager(cfg)
    network = {}
    captures = {}
    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(network))
    try:
        await manager.start("collector.ths_index_prices")
        c, q, store = (
            manager.registry.get(k)
            for k in ("collector.ths_index_prices", "index.prices.query", "redis.store")
        )
        if await store.client.xlen(store.stream):
            raise RuntimeError("待归档不为空，拒绝实采验收")
        c.selected_codes = args.codes.split(",")
        original = c.publish

        async def publish(state, cursor, dataset, code, payload, **kw):
            if dataset == "index.price.year" and payload["mode"] == "full":
                captures[f"{code}:{payload['year']}"] = dict(
                    hash=digest(payload["rows"]), count=len(payload["rows"])
                )
            result = await original(state, cursor, dataset, code, payload, **kw)
            print(
                json.dumps(
                    dict(
                        code=code,
                        unit=payload.get("year", "status"),
                        pages=result[1]["pages"],
                        collected=result[1]["collected"],
                    )
                ),
                flush=True,
            )
            return result

        c.publish = publish
        result = await asyncio.wait_for(
            c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), 1800
        )

        def compare():
            summary = {}
            with q.mysql.read_engine.begin() as conn:
                for identity, proof in captures.items():
                    code, year = identity.split(":")
                    rows = sql_rows(conn, code, int(year))
                    head = (
                        conn.execute(
                            text(
                                "SELECT * FROM index_price_year WHERE index_code=:code AND quote_year=:year"
                            ),
                            dict(code=code, year=int(year)),
                        )
                        .mappings()
                        .one()
                    )
                    assert (
                        proof["hash"] == digest(rows) == head["content_hash"]
                        and proof["count"] == len(rows) == head["row_count"]
                        and head["complete"]
                    )
                for code in c.selected_codes:
                    row = (
                        conn.execute(
                            text(
                                "SELECT COUNT(*) AS count,MIN(trade_date) AS first,MAX(trade_date) AS last FROM index_daily_price WHERE index_code=:code"
                            ),
                            dict(code=code),
                        )
                        .mappings()
                        .one()
                    )
                    summary[code] = {
                        k: str(v) if k in ("first", "last") else v for k, v in row.items()
                    }
            return summary

        summary = await q.mysql.read(compare)
        checks = await q.preparation_check(dict(index_codes=c.selected_codes))
        assert all(e.status == "pass" for e in checks), [vars(e) for e in checks]
        assert await store.client.xlen(store.stream) == 0
        settings = SettingsStore(q.mysql, store.prefix)
        saved = await settings.load("task")
        if PROJECT not in saved:
            policy = validate_policy(
                dict(
                    enabled=True,
                    mode="daily",
                    interval_seconds=86400,
                    daily_time="18:00",
                    request_retries=2,
                    use_proxy=True,
                    proxy_fallback=True,
                )
            )
            await settings.save("task", PROJECT, policy)
        report = dict(
            checked_at=datetime.now(CHINA).isoformat(),
            project=PROJECT,
            source_query_equal=True,
            policy=dict(use_proxy=True, proxy_fallback=True),
            network=network,
            range=summary,
            source_units=captures,
            preparation=[vars(e) for e in checks],
            pending=0,
            cursor=result,
            limitations="仅指定四项实际可得历史及当前修订版；其余目录未宣称采完，不提供历史可知版本，成交量保持来源口径",
        )
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
        print(
            json.dumps(
                dict(range=summary, network=network, source_units=len(captures), pending=0),
                ensure_ascii=False,
            )
        )
    finally:
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        lock.unlock()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--codes", default="399411,1A0001,399001,1B0300")
    parser.add_argument("--output", default="docs/evidence/index-prices-live-2026-10-10.json")
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
