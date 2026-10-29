"""Private typed margin capacity, actual SQL plans and repeat-DML measurement."""

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
from empire.features.margin.contract import DATASET, JOB, TABLES, pack
from empire.features.margin.dataset import MarginDataset
from empire.features.margin.query import MarginDataPlugin
from scripts.capacity_session import CapacitySession

INPUTS = tuple(
    "src/empire/features/margin/" + name + ".py"
    for name in ("contract", "source", "dataset", "query")
) + ("scripts/measure_margin.py",)


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
    mapping, fixtures, dml = MarginDataset(), [], []
    for i in range(21):
        code = f"{600000 + i:06d}.SH"
        rows = [
            [
                (date(2026, 10, 28) - timedelta(days=d)).isoformat(),
                "946.8189",
                "899791.872",
                "958",
                str(1503241 + d) + ".91",
                "107969.09",
                "10.26",
                ".32",
            ]
            for d in range(10000 if i == 0 else 500)
        ]
        rows = [r[:-1] + ["0.32"] for r in rows]
        e = make_envelope(
            source="tdx",
            dataset=DATASET,
            job_key=JOB,
            business_key=code,
            batch_id="capacity",
            run_id="capacity",
            schema_version=1,
            payload=dict(page=i + 1, code=code, through="2026-10-30", rows=pack(rows)),
        )
        fixtures.append((e, mapping.normalize(e)))

    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "margin_" in sql:
            dml.append(sql)

    with capacity:
        engine = capacity.engine
        with engine.begin() as conn:
            for ddl in statements.values():
                conn.exec_driver_sql(ddl)
        tracemalloc.start()
        started = time.perf_counter()
        unit_times = []
        for e, data in fixtures:
            at = time.perf_counter()
            with engine.begin() as conn:
                mapping.write(conn, e, {**data, "archive_state": {}})
            unit_times.append(time.perf_counter() - at)
        imported = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.listen(engine, "before_cursor_execute", capture)
        for e, data in fixtures:
            with engine.begin() as conn:
                mapping.write(conn, e, {**data, "archive_state": {}})
        event.remove(engine, "before_cursor_execute", capture)
        q = MarginDataPlugin()

        async def read(fn, *args):
            return fn(*args)

        q.mysql = SimpleNamespace(engine=engine, read_engine=engine, read=read)
        pages = []
        histories = []
        for _ in range(10):
            at = time.perf_counter()
            page = await q.browse()
            pages.append((time.perf_counter() - at) * 1000)
            at = time.perf_counter()
            history = await q.history("600000.SH")
            histories.append((time.perf_counter() - at) * 1000)
        assert len(history) == 10000
        plans = {}
        with engine.connect() as conn:
            for label, sql in dict(
                page="SELECT * FROM margin_daily ORDER BY trade_date DESC,unified_code DESC LIMIT 200",
                security="SELECT * FROM margin_daily WHERE unified_code='600000.SH' ORDER BY trade_date DESC LIMIT 10000",
                analysis="SELECT trade_date,SUM(financing_balance) FROM margin_daily WHERE trade_date BETWEEN '2026-10-01' AND '2026-10-28' GROUP BY trade_date",
            ).items():
                plans[label] = [dict(r) for r in conn.exec_driver_sql("EXPLAIN " + sql).mappings()]
                plans[label + "_actual_rows"] = len(conn.exec_driver_sql(sql).all())
            conn.exec_driver_sql("ANALYZE TABLE " + ",".join(TABLES)).all()
            allocation = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT table_name,data_length,index_length FROM information_schema.tables WHERE table_schema=:db"
                    ),
                    dict(db=capacity.database),
                ).mappings()
            ]
        allocated = sum(int(r["DATA_LENGTH"]) + int(r["INDEX_LENGTH"]) for r in allocation)
        measured = dict(
            import_seconds=imported,
            max_unit_seconds=max(unit_times),
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
            max_unit_seconds=10,
            repeated_business_dml=0,
            page_p95_ms=100,
            history_p95_ms=1000,
            allocated_bytes=32 * 1024**2,
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
                securities=21,
                rows=20000,
                allocation=allocation,
                cache="first query not forced cold; remaining nine warm; maximum bounds P95",
                actual_sample="5% source verification recorded separately",
                peak="tracemalloc allocations, not RSS",
            ),
            projected_five_year_bytes=allocated * 7500000 // 20000,
            reviewed_tradeoffs="Core values typed; one complete-security snapshot, comparison bounded to10000 rows. Derived fields computed at query; indexed predecessor bounded to201 records. No JSON business payload.",
        )
        if any(measured[k] > v for k, v in limits.items()):
            raise ValueError("Capacity budget exceeded: " + str(measured))
        capacity.measurements_complete = True
    print("PASS margin capacity", measured)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--test-settings", required=True)
    p.add_argument("--report", required=True)
    asyncio.run(run(p.parse_args()))
