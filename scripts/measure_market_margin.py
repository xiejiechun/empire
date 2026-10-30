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
from empire.features.market_margin.contract import DATASET, JOB, TABLES, pack
from empire.features.market_margin.dataset import MarketMarginDataset
from empire.features.market_margin.query import MarketMarginDataPlugin
from scripts.capacity_session import CapacitySession

INPUTS = tuple(
    "src/empire/features/market_margin/" + name + ".py"
    for name in ("contract", "source", "dataset", "query")
) + ("scripts/measure_market_margin.py",)


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
    mapping, fixtures, dml = MarketMarginDataset(), [], []
    for i, code in enumerate(("99", "3", "2", "4")):
        first = date(2023, 2, 13) if code == "4" else date(2010, 3, 31)
        rows = [
            [
                (first + timedelta(days=d)).isoformat(),
                "1503241.91",
                "100",
                "200",
                "-10",
                "20",
                None,
                None,
                "0.012121262302321",
                "1503341.91" if code == "99" else None,
            ]
            for d in range(10000)
        ]
        e = make_envelope(
            source="ths",
            dataset=DATASET,
            job_key=JOB,
            business_key=code,
            batch_id="capacity",
            run_id="capacity",
            schema_version=1,
            payload=dict(page=i + 1, code=code, through="2051-01-01", rows=pack(rows)),
        )
        fixtures.append((e, {**e.raw_payload, "rows": rows, "row_count": len(rows)}))

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
        q = MarketMarginDataPlugin()

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
            history = await q.history("99")
            histories.append((time.perf_counter() - at) * 1000)
        assert len(history) == 10000
        plans = {}
        with engine.connect() as conn:
            for label, sql in dict(
                page="SELECT * FROM market_margin_daily ORDER BY trade_date DESC,market_code DESC LIMIT 200",
                security="SELECT * FROM market_margin_daily WHERE market_code='99' ORDER BY trade_date DESC LIMIT 10000",
                analysis="SELECT trade_date,SUM(financing_balance) FROM market_margin_daily WHERE market_code='99' AND trade_date BETWEEN '2026-10-01' AND '2026-10-28' GROUP BY trade_date",
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
                markets=4,
                rows=40000,
                allocation=allocation,
                cache="first query not forced cold; remaining nine warm; maximum bounds P95",
                actual_sample="5% source verification recorded separately",
                peak="tracemalloc allocations, not RSS",
            ),
            projected_five_year_bytes=allocated * 5000 // 40000,
            reviewed_tradeoffs="Four complete market snapshots; comparison bounded to10000 dates per market; bounded keyset SQL browsing. No business JSON.",
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
