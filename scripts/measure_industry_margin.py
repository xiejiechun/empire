"""Isolated SQL capacity and bounded query measurements for complete industry dates."""

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
from empire.features.industry_margin.contract import DATASET, JOB, TABLES
from empire.features.industry_margin.dataset import IndustryMarginDataset
from empire.features.industry_margin.query import IndustryMarginDataPlugin
from scripts.capacity_session import CapacitySession

INPUTS = tuple(
    "src/empire/features/industry_margin/" + n + ".py"
    for n in ("contract", "source", "dataset", "query")
) + ("scripts/measure_industry_margin.py",)


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
    mapping, fixtures, dml = IndustryMarginDataset(), [], []
    for i in range(400):
        stamp = (date(2020, 1, 1) + timedelta(days=i)).isoformat()
        rows = [
            [
                f"industry-{j:03d}",
                "1595.798375",
                "107.409601",
                "5.35288",
                "5.396539",
                "20.12",
                "55.0873",
                "196.4715",
            ]
            for j in range(256 if i == 0 else 30)
        ]
        envelope = make_envelope(
            source="tdx",
            dataset=DATASET,
            job_key=JOB,
            business_key=stamp,
            batch_id="capacity",
            run_id="capacity",
            schema_version=1,
            payload=dict(page=i + 1, date=stamp, rows=rows, source_latest="2026-10-28"),
        )
        fixtures.append((envelope, mapping.normalize(envelope)))

    def capture(conn, cursor, sql, parameters, context, many):
        if (
            sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "industry_margin_" in sql
        ):
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
        q = IndustryMarginDataPlugin()

        async def read(fn, *args):
            return fn(*args)

        q.mysql = SimpleNamespace(engine=engine, read_engine=engine, read=read)
        pages, histories = [], []
        for _ in range(10):
            at = time.perf_counter()
            page = await q.browse()
            pages.append((time.perf_counter() - at) * 1000)
            at = time.perf_counter()
            history = await q.history("2020-01-01")
            histories.append((time.perf_counter() - at) * 1000)
        assert len(history) == 256
        plans = {}
        with engine.connect() as conn:
            for label, sql in dict(
                page="SELECT * FROM industry_margin_daily ORDER BY trade_date DESC,industry_name DESC LIMIT 200",
                industry="SELECT * FROM industry_margin_daily WHERE industry_name='industry-001' ORDER BY trade_date DESC LIMIT 200",
                analysis="SELECT trade_date,SUM(financing_balance) FROM industry_margin_daily WHERE trade_date BETWEEN '2020-01-01' AND '2020-01-31' GROUP BY trade_date",
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
            import_seconds=60,
            max_unit_seconds=1,
            repeated_business_dml=0,
            page_p95_ms=100,
            history_p95_ms=1000,
            allocated_bytes=32 * 1024**2,
            peak_python_bytes=128 * 1024**2,
            page_bytes=262144,
            history_bytes=262144,
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
                dates=400,
                rows=12226,
                allocation=allocation,
                cache="first query not forced cold; nine subsequent warm; maximum bounds P95",
                actual_sample="5% source verification recorded separately",
                peak="tracemalloc not RSS",
            ),
            projected_five_year_bytes=allocated * 55000 // 12226,
            reviewed_tradeoffs="Typed daily source facts; complete-date aggregate proof; no business JSON; 31-day bounded audit batches.",
        )
        if any(measured[k] > v for k, v in limits.items()):
            raise ValueError("Capacity budget exceeded: " + str(measured))
        capacity.measurements_complete = True
    print("PASS industry margin capacity", measured)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--test-settings", required=True)
    p.add_argument("--report", required=True)
    asyncio.run(run(p.parse_args()))
