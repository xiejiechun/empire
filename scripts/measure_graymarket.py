"""Isolated SQL capacity and bounded query measurements for complete security dates."""

import argparse
import asyncio
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.graymarket.codec import pack
from empire.features.graymarket.contract import DATASET, JOB, TABLES
from empire.features.graymarket.dataset import GraymarketDataset
from empire.features.graymarket.query import GraymarketDataPlugin
from scripts.capacity_session import CapacitySession

INPUTS = tuple(
    "src/empire/features/graymarket/" + n + ".py"
    for n in ("contract", "source", "codec", "dataset", "query")
) + ("scripts/measure_graymarket.py",)


async def run(args):
    root = Path(__file__).resolve().parents[1]
    capacity = CapacitySession(
        load_config()["mysql"],
        json.loads(Path(args.test_settings).read_text("utf-8")),
        root=root,
        subject="preview",
        output=args.report,
        input_paths=INPUTS,
    )
    schema = (root / "sql/schema.sql").read_text("utf-8")
    statements = {
        t: re.search(r"CREATE TABLE IF NOT EXISTS " + t + r"\s*\([\s\S]*?;", schema)[0]
        for t in TABLES
    }
    mapping, fixtures, dml = GraymarketDataset(), [], []
    total_rows = 0
    for i in range(20):
        stamp = (date(2026, 6, 1) + timedelta(days=i)).isoformat()
        rows = [
            [
                f"{j:06d}.SZ",
                "capacity",
                str(1000000 - j),
                "-100",
                str(999900 - j),
                "0.12712",
                "71.54",
                "-0.09572",
                "153439",
                j + 1,
            ]
            for j in range(10000 if i == 0 else 5377)
        ]
        total_rows += len(rows)
        envelope = make_envelope(
            source="eastmoney",
            dataset=DATASET,
            job_key=JOB,
            business_key=stamp,
            batch_id="capacity",
            run_id="capacity",
            schema_version=1,
            payload=dict(page=i + 1, date=stamp, rows=pack(rows), source_latest="2026-11-02"),
        )
        fixtures.append((envelope, mapping.normalize(envelope)))

    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "graymarket_" in sql:
            dml.append(sql)

    with capacity:
        engine = capacity.engine
        with engine.begin() as conn:
            for ddl in statements.values():
                conn.exec_driver_sql(ddl)
        tracemalloc.start()
        started = time.perf_counter()
        times = []
        for e, data in fixtures:
            at = time.perf_counter()
            with engine.begin() as conn:
                mapping.write(conn, e, {**data, "archive_state": {}})
            times.append(time.perf_counter() - at)
        imported = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.listen(engine, "before_cursor_execute", capture)
        for e, data in fixtures:
            with engine.begin() as conn:
                mapping.write(conn, e, {**data, "archive_state": {}})
        event.remove(engine, "before_cursor_execute", capture)
        q = GraymarketDataPlugin()

        async def read(fn, *args):
            return fn(*args)

        q.mysql = SimpleNamespace(engine=engine, read_engine=engine, read=read)
        pages, histories = [], []
        for _ in range(10):
            at = time.perf_counter()
            page = await q.browse()
            pages.append((time.perf_counter() - at) * 1000)
            at = time.perf_counter()
            history = await q.history("2026-06-01")
            histories.append((time.perf_counter() - at) * 1000)
        assert len(history) == 10000
        plans = {}
        with engine.connect() as conn:
            for label, sql in dict(
                page="SELECT * FROM graymarket_daily ORDER BY trade_date DESC,unified_code DESC LIMIT 200",
                industry="SELECT * FROM graymarket_daily WHERE unified_code='000001.SZ' ORDER BY trade_date DESC LIMIT 200",
                analysis="SELECT trade_date,SUM(dark_flow) FROM graymarket_daily WHERE trade_date BETWEEN '2026-06-01' AND '2026-06-20' GROUP BY trade_date",
            ).items():
                plans[label] = [dict(r) for r in conn.exec_driver_sql("EXPLAIN " + sql).mappings()]
                plans[label + "_actual_rows"] = len(conn.exec_driver_sql(sql).all())
            conn.exec_driver_sql("ANALYZE TABLE " + ",".join(TABLES)).all()
            allocation = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT table_name,data_length,index_length "
                        "FROM information_schema.tables WHERE table_schema=:db"
                    ),
                    dict(db=capacity.database),
                ).mappings()
            ]
        allocated = sum(int(r["DATA_LENGTH"]) + int(r["INDEX_LENGTH"]) for r in allocation)
        measured = dict(
            import_seconds=imported,
            max_unit_seconds=max(times),
            repeated_business_dml=len(dml),
            page_p95_ms=max(pages),
            history_p95_ms=max(histories),
            allocated_bytes=allocated,
            peak_python_bytes=peak,
            page_bytes=len(json.dumps(page, default=str).encode()),
            history_bytes=len(json.dumps(history).encode()),
        )
        limits = dict(
            import_seconds=120,
            max_unit_seconds=5,
            repeated_business_dml=0,
            page_p95_ms=300,
            history_p95_ms=5000,
            allocated_bytes=128 * 1024**2,
            peak_python_bytes=128 * 1024**2,
            page_bytes=262144,
            history_bytes=4 * 1024**2,
        )
        capacity.report.update(
            dataset=DATASET,
            measurements=measured,
            limits=limits,
            bindings=capacity.frozen_inputs,
            ddl_scopes={
                t: hashlib.sha256(ddl.encode()).hexdigest() for t, ddl in statements.items()
            },
            explain=plans,
            conditions=dict(
                platform=platform.platform(),
                mysql=capacity.identity,
                synthetic=True,
                dates=20,
                rows=total_rows,
                allocation=allocation,
                cache="first query not forced cold; nine subsequent warm; maximum bounds P95",
                actual_sample="5% source verification recorded separately",
                peak="tracemalloc not RSS",
            ),
            projected_five_year_bytes=allocated * 6721250 // total_rows,
            reviewed_tradeoffs="Typed daily source facts; complete-date aggregate proof; no business JSON; per-day bounded audits.",
        )
        if any(measured[k] > v for k, v in limits.items()):
            raise ValueError("Capacity budget exceeded: " + str(measured))
        capacity.measurements_complete = True
    print("PASS graymarket capacity", measured)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--test-settings", required=True)
    p.add_argument("--report", required=True)
    asyncio.run(run(p.parse_args()))
