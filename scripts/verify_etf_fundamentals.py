"""Seeded ~5% complete ETF histories/source dates through the formal isolated pipeline."""

import argparse
import asyncio
import copy
import json
import math
import random
from pathlib import Path

from capacity_session import CapacitySession
from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.etf_fundamentals.contract import NAV_FIELDS, NUMERIC, START, digest, number
from empire.plugins.infra.mysql_store import initialize_database
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

SEED = 20261117
FIXED = [
    "510050.SH",
    "510300.SH",
    "511120.SH",
    "511880.SH",
    "511990.SH",
    "551900.SH",
    "159001.SZ",
    "159915.SZ",
    "513100.SH",
    "518880.SH",
]


async def collect(session, config):
    cfg = copy.deepcopy(config)
    cfg["mysql"], cfg["redis"]["namespace"] = session.settings, "empire:test:" + session.run_id
    initialize_database(cfg["mysql"])
    with session.source_engine.connect() as conn:
        session.require_source(conn)
        conn.exec_driver_sql("START TRANSACTION READ ONLY")
        catalog = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT unified_code AS code,name,native_market FROM yuanhang_etf WHERE active=TRUE ORDER BY unified_code LIMIT 5001"
                )
            ).mappings()
        ]
        calendar = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT trade_date,is_trade,updated_at FROM trade_calendar ORDER BY trade_date LIMIT 54901"
                )
            ).mappings()
        ]
        network_settings = [dict(r) for r in conn.execute(text(
            "SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns "
            "AND kind IN ('site','download') ORDER BY kind,setting_key LIMIT 50"
        ), dict(ns=config["redis"]["namespace"])).mappings()]
        conn.rollback()
    codes = [r["code"] for r in catalog]
    if not set(FIXED) <= set(codes) or not 1 <= len(codes) <= 5000:
        raise ValueError("ETF固定反例不在可信当前目录")
    size = math.ceil(len(codes) * 0.05)
    sample = sorted(
        FIXED + random.Random(SEED).sample(sorted(set(codes) - set(FIXED)), size - len(FIXED))
    )
    from datetime import datetime

    from empire.core.time import CHINA
    from empire.features.calendar.contract import last_closed_trade_day

    cutoff, reason = last_closed_trade_day(calendar, datetime.now(CHINA))
    if cutoff is None:
        raise ValueError(reason)
    through = cutoff.date().isoformat()
    dates = [
        r["trade_date"].isoformat()
        for r in calendar
        if r["is_trade"] and START <= r["trade_date"].isoformat() <= through
    ]
    fixed_dates = sorted(
        set([dates[-1], dates[-2], dates[-3], "2015-01-05", "2020-01-02"]) & set(dates)
    )
    count = math.ceil(len(dates) * 0.05)
    chosen_dates = sorted(
        fixed_dates
        + random.Random(SEED).sample(
            sorted(set(dates) - set(fixed_dates)), count - len(fixed_dates)
        )
    )
    with session.engine.begin() as conn:
        for item in network_settings:
            conn.execute(text("INSERT INTO app_setting(namespace,kind,setting_key,payload) "
                "VALUES(:ns,:kind,:setting_key,:payload)"), dict(ns=cfg["redis"]["namespace"], **item))
        conn.execute(
            text(
                "INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:trade_date,:is_trade,:updated_at)"
            ),
            calendar,
        )
        conn.execute(
            text(
                "INSERT INTO yuanhang_etf(unified_code,name,native_market,active) VALUES(:code,:name,:native_market,TRUE)"
            ),
            catalog,
        )
        conn.execute(
            text(
                "INSERT INTO collection_state(namespace,project_id,source,dataset,payload,updated_at) VALUES(:ns,'ths-yuanhang-etfs','ths_yuanhang','yuanhang.etf.catalog',:payload,NOW())"
            ),
            dict(
                ns=cfg["redis"]["namespace"],
                payload=json.dumps(dict(catalog_hash=digest(catalog), count=len(catalog))),
            ),
        )
    session.report.update(
        seed=SEED,
        catalog_count=len(codes),
        catalog_hash=digest(catalog),
        sample=sample,
        sample_fraction=len(sample) / len(codes),
        share_date_population=len(dates),
        share_dates=chosen_dates,
        share_fraction=len(chosen_dates) / len(dates),
        through=through,
        fixed=FIXED,
        network_settings_copied_to_private_database=len(network_settings),
    )
    manager, routes, proofs = build_manager(cfg), {}, {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(routes)
    try:
        for project in ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav"):
            await manager.start("collector." + project.replace("-", "_"))
            c = manager.registry.get("collector." + project.replace("-", "_"))
            original = c.fetch_unit

            async def capture(unit, *, reservation, fetch=original, source=c.source):
                rows, observed = await fetch(unit, reservation=reservation)
                identity = unit.get("code", unit.get("date"))
                proofs[(source, identity)] = dict(count=len(rows), hash=digest(rows), unit=unit)
                if source == "ttjj":
                    print(f"Downloaded full NAV unit {identity}: {len(rows)} facts", flush=True)
                return rows, observed

            c.fetch_unit = capture
            print(
                f"Collecting {project}: {len(sample) if c.source == 'ttjj' else len(chosen_dates) - 1} complete units",
                flush=True,
            )
            kw = (
                dict(codes=sample, start=START, end=dates[-2])
                if c.source == "ttjj"
                else dict(sample_dates=[d for d in chosen_dates if d != through])
            )
            await c.execute(**kw)
            session.report["source_proofs"] = {s + ":" + i: p for (s, i), p in proofs.items()}
            print(
                f"Archived {project}: {c.stats['collected']} facts, {c.stats['requests']} source requests",
                flush=True,
            )
        q = manager.registry.get("etf.fundamentals.query")
        for (source, identity), proof in proofs.items():
            unit = proof["unit"]
            values = []
            after = None
            while True:
                result = await q.browse(
                    source=source,
                    code=unit.get("code", ""),
                    start=unit.get("start", unit.get("date")),
                    end=unit.get("through", unit.get("date")),
                    after=after,
                    limit=500,
                )
                for r in result["rows"]:
                    if source == "ttjj":
                        values.append(
                            [
                                r["nav_date"],
                                *[number(r[f]) if f in NUMERIC else r[f] for f in NAV_FIELDS],
                            ]
                        )
                    else:
                        values.append(
                            [
                                r["unified_code"],
                                r["name"],
                                number(r["total_shares"]),
                                r["source_group"],
                                r["source_type"],
                            ]
                        )
                after = result["next"]
                if after is None:
                    break
            if len(values) != proof["count"] or digest(sorted(values)) != proof["hash"]:
                raise ValueError("ETF正式查询与源端完整集合/内容不一致：" + source + ":" + identity)
        session.report["initial_proofs"] = {s + ":" + i: p for (s, i), p in proofs.items()}
        for project in ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav"):
            c = manager.registry.get("collector." + project.replace("-", "_"))
            kw = (
                dict(codes=sample, start=dates[-10], end=through)
                if c.source == "ttjj"
                else dict(sample_dates=[through])
            )
            await c.execute(baseline_revision=await c.checkpoint_revision(), **kw)
            # One necessary maintenance read per selected range; same content must not change facts.
            await c.execute(baseline_revision=await c.checkpoint_revision(), **kw)
            redis = manager.registry.get("redis.store")
            await redis.client.delete(redis.prefix + ":checkpoint:" + c.job_key)
            await c.execute(**kw)
            print(f"Increment, repeat, checkpoint-loss recovery passed: {project}", flush=True)
        redis = manager.registry.get("redis.store")
        pending = await redis.client.xlen(redis.stream)
        if pending:
            raise ValueError("ETF整轮归档未清队")
        session.report.update(
            pending=pending,
            routes=routes,
            untested="未抽中的证券、日期；来源未披露字段；全历史旧版本及严格公布时点",
            statuses={
                p: dict(manager.registry.get("collector." + p.replace("-", "_")).stats)
                for p in ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav")
            },
        )
    finally:
        session.report["statuses"] = {
            p: dict(manager.registry.get("collector." + p.replace("-", "_")).stats)
            for p in ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav")
            if manager.registry.optional("collector." + p.replace("-", "_"))
        }
        records = manager.registry.optional("collection.records")
        if records:
            session.report["errors_by_project"] = {
                p: await records.list_error_summaries(p, limit=100)
                for p in ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav")
            }
        session.report["routes"] = routes
        await manager.shutdown()
        for var, token in zip((USE_PROXY, PROXY_FALLBACK, ROUTE_COUNTS), tokens, strict=True):
            var.reset(token)
        client = create_client(cfg["redis"])
        try:
            keys = [k async for k in client.scan_iter(match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()


def main(args):
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(args.config)
    paths = [
        p.relative_to(root).as_posix()
        for p in (root / "src/empire/features/etf_fundamentals").glob("*.py")
    ]
    paths += ["scripts/verify_etf_fundamentals.py", "scripts/capacity_session.py"]
    with CapacitySession(
        cfg["mysql"],
        json.loads(Path(args.test_mysql).read_text("utf8")),
        root=root,
        subject="indices",
        output=args.output,
        input_paths=paths,
    ) as session:
        session.report["bindings"] = session.frozen_inputs
        session.report["feature"] = "etf-fundamentals"
        session.report["network_policy"] = dict(use_proxy=True, proxy_fallback=True)
        asyncio.run(collect(session, cfg))
        session.measurements_complete = True
    print(
        "PASS bounded real ETF sample, formal content equality and whole-round clean queue",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--test-mysql", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        main(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
