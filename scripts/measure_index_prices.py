"""Private MySQL capacity and range-index evidence; no production business writes."""

import argparse
import asyncio
import hashlib
import json
import platform
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.index_prices import JOB
from empire.core.config import load_config, project_root
from empire.plugins.data.index_prices import IndexPriceDataPlugin
from empire.plugins.datasets import index_prices
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text("utf8"))
    production = load_config()["mysql"]
    if (settings.get("host"), settings.get("port")) == (
        production.get("host"),
        production.get("port"),
    ):
        raise ValueError("容量实验必须使用独立MySQL服务")
    admin = make_engine(settings)
    database = "empire_" + uuid4().hex + "_test"
    engine = None
    created = False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
            created = True
        settings = {**settings, "database": database}
        initialize_database(settings)
        engine = make_engine(settings)
        state = {}
        observed = datetime.now(UTC)
        rows = [
            [
                (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                "10",
                "12",
                "9",
                "11",
                "100",
                "1000",
            ]
            for i in range(100)
        ]

        def archive(code, values):
            nonlocal state
            e = make_envelope(
                source="ths",
                dataset="index.price.year",
                business_key=code + ":2025",
                job_key=JOB,
                batch_id="capacity",
                run_id="capacity",
                payload=dict(
                    page=1,
                    code=code,
                    year=2025,
                    mode="full",
                    source_count=100,
                    start=rows[0][0],
                    end=rows[-1][0],
                    rows=values,
                ),
            ).model_copy(update={"observed_at": observed})
            data = index_prices.normalize(e)
            with engine.begin() as conn:
                outcome = index_prices.write(conn, e, {**data, "archive_state": state})
            state = index_prices.archive_state(e, data, outcome, state)
            return outcome

        started = time.perf_counter()
        for i in range(1000):
            archive(f"{i:06d}", rows)
        imported = time.perf_counter() - started
        repeat = archive("000000", rows)
        revision = [list(r) for r in rows]
        revision[0][4] = "11.5"
        revised = archive("000000", revision)
        assert repeat["written_count"] == 0 and revised["written_count"] == 2
        q = IndexPriceDataPlugin()
        q.mysql = type("ReadOnly", (), dict(read_engine=engine))()

        # Invoke the public query without creating extra SQL lane objects.
        async def read(operation, *args):
            return operation(*args)

        q.mysql.read = read
        measurements = {}
        for name, options in [
            ("index_page", dict(code="000001")),
            ("date_page", dict(start="2025-02-01", end="2025-03-01")),
        ]:
            values = []
            for _ in range(20):
                start = time.perf_counter()
                result = asyncio.run(q.browse(**options))
                values.append((time.perf_counter() - start) * 1000)
                assert result["rows"]
            measurements[name + "_p95_ms"] = sorted(values)[18]
        with engine.connect() as conn:
            conn.exec_driver_sql("ANALYZE TABLE index_daily_price,index_price_year")
            allocated = conn.execute(
                text(
                    "SELECT SUM(DATA_LENGTH+INDEX_LENGTH) FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db AND TABLE_NAME IN ('index_daily_price','index_price_year')"
                ),
                dict(db=database),
            ).scalar_one()
            explains = {
                name: [dict(r) for r in conn.exec_driver_sql(sql).mappings()]
                for name, sql in {
                    "index_date": "EXPLAIN SELECT * FROM index_daily_price WHERE index_code='000001' AND trade_date>='2025-02-01' ORDER BY trade_date LIMIT 200",
                    "all_date": "EXPLAIN SELECT * FROM index_daily_price WHERE trade_date>='2025-02-01' AND trade_date<='2025-03-01' ORDER BY trade_date,index_code LIMIT 200",
                }.items()
            }
            version = conn.exec_driver_sql("SELECT VERSION()").scalar_one()
        measurements.update(
            import_seconds=imported,
            allocated_bytes=int(allocated),
            state_bytes=len(json.dumps(state).encode()),
        )
        paths = [
            "src/empire/contracts/index_prices.py",
            "src/empire/plugins/datasets/index_prices.py",
            "src/empire/plugins/data/index_prices.py",
            "scripts/measure_index_prices.py",
        ]
        schema = (root / "sql/schema.sql").read_text("utf8")
        report = dict(
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={
                t: hashlib.sha256(
                    re.search(r"CREATE TABLE IF NOT EXISTS " + t + r"\s*\([\s\S]*?;", schema)
                    .group()
                    .encode()
                ).hexdigest()
                for t in index_prices.TABLES
            },
            measurements=measurements,
            limits=dict(
                index_page_p95_ms=50,
                date_page_p95_ms=50,
                import_seconds=30,
                allocated_bytes=64 * 1024**2,
                state_bytes=8 * 1024**2,
            ),
            conditions=dict(
                platform=platform.platform(),
                mysql=version,
                rows=100000,
                indices=1000,
                synthetic=True,
                repeat_business_dml=repeat["written_count"],
                revision_writes=revised["written_count"],
                repeats=20,
                cache="unforced MySQL warm repeats; Redis not used",
            ),
            reviewed_tradeoffs="年度聚合证明与结构化日行；双向日期索引，主键游标分页。100000合成日行不代表全目录实采或全部历史容量；总2GiB为规划预算。状态只保留观察版本，无日线正文。",
            explain=explains,
            cleanup="UUID-owned schema dropped in finally",
        )
        report["passed"] = all(measurements[k] <= v for k, v in report["limits"].items())
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
        print(json.dumps(dict(passed=report["passed"], measurements=measurements)))
        if not report["passed"]:
            raise RuntimeError("指数日线容量预算未通过")
    finally:
        if engine:
            engine.dispose()
        if created:
            assert database.endswith("_test")
            with admin.connect() as conn:
                conn.exec_driver_sql(f"DROP DATABASE `{database}`")
        admin.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-settings", required=True)
    parser.add_argument("--output", default="docs/evidence/index-prices-capacity-2026-10-10.json")
    run(parser.parse_args())
