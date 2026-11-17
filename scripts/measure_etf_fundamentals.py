"""Measure the four ETF fact/proof tables through their official writers and reads."""

import argparse
import asyncio
import json
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from capacity_session import CapacitySession
from create_name_change_schema import ddl
from schema_evidence_scope import objects
from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.core.config import load_config, project_root
from empire.features.etf_fundamentals import nav_dataset, share_dataset
from empire.features.etf_fundamentals.contract import NAV_FIELDS, TABLES, digest
from empire.features.etf_fundamentals.query import Query
from empire.features.market_review.etf_flows import read_etf_flows
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.collection_state_unit import read_unit, save_unit


def run(args):
    root = project_root()
    paths = [
        p.relative_to(root).as_posix()
        for p in (root / "src/empire/features/etf_fundamentals").glob("*.py")
    ]
    paths += [
        "scripts/measure_etf_fundamentals.py",
        "scripts/capacity_session.py",
        "src/empire/features/market_review/etf_flows.py",
    ]
    with CapacitySession(
        load_config(args.config)["mysql"],
        json.loads(Path(args.test_mysql).read_text("utf8")),
        root=root,
        subject="indices",
        output=args.output,
        input_paths=paths,
    ) as session:
        engine = session.engine
        with engine.begin() as conn:
            for table in (*TABLES, "collection_state", "yuanhang_etf"):
                conn.exec_driver_sql(ddl(table))
        observed = datetime.now(UTC)

        def archive(mapping, payload, stamp=observed):
            nav = mapping is nav_dataset
            source, project = ("ttjj", "ttjj-etf-nav") if nav else ("sse", "sse-etf-shares")
            key = payload["code"] + ":2025" if nav else payload["date"]
            envelope = make_envelope(
                source=source,
                dataset=next(iter(mapping.DATASETS)),
                business_key=key,
                job_key=project + "-v1",
                batch_id="capacity",
                run_id="capacity",
                payload=dict(page=1, **payload),
            ).model_copy(update={"observed_at": stamp})
            data = mapping.normalize(envelope)
            with engine.begin() as conn:
                previous, exists = (
                    read_unit(conn, "capacity", project, source, payload["code"])
                    if nav
                    else (read_state(conn, "capacity", project, source), True)
                )
                outcome = mapping.write(conn, envelope, {**data, "archive_state": previous})
                updated = mapping.archive_state(envelope, data, outcome, previous)
                if nav:
                    save_unit(
                        conn,
                        "capacity",
                        project,
                        source,
                        mapping.FINGERPRINT_NAMESPACE,
                        payload["code"],
                        updated,
                        previous,
                        exists,
                    )
                else:
                    save_state(
                        conn,
                        "capacity",
                        project,
                        source,
                        mapping.FINGERPRINT_NAMESPACE,
                        updated,
                        previous,
                    )
            return outcome

        first = date(2025, 1, 1)
        catalog = [
            dict(code=f"{i:06}.SH", name=f"容量ETF{i}", native_market="USHJ") for i in range(2500)
        ]
        shares = [[r["code"], r["name"], "123456789.123456789", "etf", None] for r in catalog]
        values = [
            [
                (first + timedelta(days=i)).isoformat(),
                *[
                    dict(
                        value_kind="nav",
                        unit_nav="1.123456789",
                        accumulated_nav="1.3",
                        daily_change_pct="-0.1",
                        purchase_status="开放申购",
                        redemption_status="开放赎回",
                        distribution_text="每10份派0.1元",
                        fund_type="001",
                    ).get(f)
                    for f in NAV_FIELDS
                ],
            ]
            for i in range(250)
        ]
        started = time.perf_counter()
        message_sizes = []
        for i in range(40):
            payload = dict(date=(first + timedelta(days=i)).isoformat(), rows=shares)
            archive(share_dataset, payload)
            message_sizes.append(len(json.dumps(payload, ensure_ascii=False).encode()))
        share_seconds = time.perf_counter() - started
        started = time.perf_counter()
        for i in range(400):
            payload = dict(code=f"{i:06}.SH", start="2025-01-01", through="2025-12-31", rows=values)
            archive(nav_dataset, payload)
            message_sizes.append(len(json.dumps(payload, ensure_ascii=False).encode()))
        nav_seconds = time.perf_counter() - started
        share_payload = dict(date="2025-01-01", rows=shares)
        nav_payload = dict(code="000000.SH", start="2025-01-01", through="2025-12-31", rows=values)
        repeated = [archive(share_dataset, share_payload), archive(nav_dataset, nav_payload)]
        changed_share = [list(r) for r in shares]
        changed_share[0][2] = "123456790.123456789"
        changed_nav = [list(r) for r in values]
        changed_nav[0][2] = "1.2"
        revised = [
            archive(
                share_dataset,
                {**share_payload, "rows": changed_share},
                observed + timedelta(seconds=1),
            ),
            archive(
                nav_dataset, {**nav_payload, "rows": changed_nav}, observed + timedelta(seconds=1)
            ),
        ]
        assert all(r["written_count"] == 0 for r in repeated)
        assert all(r["written_count"] == 2 for r in revised)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO yuanhang_etf(unified_code,name,native_market,active) VALUES(:code,:name,:native_market,TRUE)"
                ),
                catalog,
            )
            save_state(
                conn,
                "capacity",
                "ths-yuanhang-etfs",
                "ths_yuanhang",
                "capacity",
                dict(catalog_hash=digest(catalog), count=len(catalog)),
                {},
            )

        async def read(callback):
            return callback()

        query = Query("capacity")
        query.mysql = SimpleNamespace(read_engine=engine, read=read)
        calendar = {first + timedelta(days=i): True for i in range(40)}

        def review():
            with engine.connect() as conn:
                return read_etf_flows(
                    conn,
                    first + timedelta(days=39),
                    first + timedelta(days=38),
                    calendar,
                    "capacity",
                )

        async def measure():
            measurements, details = {}, {}
            for label, callback in (
                (
                    "nav_year",
                    lambda: query.browse(
                        code="000001.SH", start="2025-01-01", end="2025-12-31", limit=500
                    ),
                ),
                (
                    "share_day",
                    lambda: query.browse(source="sse", start="2025-01-02", end="2025-01-02"),
                ),
                ("nav_day", lambda: query.browse(start="2025-01-02", end="2025-01-02")),
            ):
                samples, sizes, counts = [], [], []
                for _ in range(21):
                    before = time.perf_counter()
                    result = await callback()
                    samples.append((time.perf_counter() - before) * 1000)
                    counts.append(len(result["rows"]))
                    sizes.append(len(json.dumps(result, default=str, ensure_ascii=False).encode()))
                assert all(counts)
                measurements[label + "_p95_ms"] = sorted(samples[1:])[18]
                details[label] = dict(
                    first_ms=samples[0], warm_ms=samples[1:], rows=counts, encoded_bytes=sizes
                )
            samples = []
            for _ in range(21):
                before = time.perf_counter()
                result = review()
                samples.append((time.perf_counter() - before) * 1000)
                assert result["current"]["candidate_count"] == 400
            measurements["review_p95_ms"] = sorted(samples[1:])[18]
            details["review"] = dict(first_ms=samples[0], warm_ms=samples[1:], candidates=400)
            return measurements, details

        measurements, details = asyncio.run(measure())
        tracemalloc.start()
        share_dataset.normalize(
            SimpleNamespace(
                business_key="2025-01-01", source="sse", raw_payload=dict(page=1, **share_payload)
            )
        )
        nav_dataset.normalize(
            SimpleNamespace(
                business_key="000000.SH:2025",
                source="ttjj",
                raw_payload=dict(page=1, **nav_payload),
            )
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        started = time.perf_counter()
        with engine.connect() as conn:
            for i in range(40):
                day = (first + timedelta(days=i)).isoformat()
                rows = share_dataset.read_rows(conn, "sse", day)
                assert rows == (changed_share if i == 0 else shares)
                head = conn.execute(
                    text(
                        "SELECT content_hash FROM etf_share_day WHERE source='sse' AND share_date=:d"
                    ),
                    dict(d=day),
                ).scalar_one()
                assert head == digest(rows)
            for i in range(400):
                rows = nav_dataset.read_rows(conn, f"{i:06}.SH", 2025)
                assert rows == (changed_nav if i == 0 else values)
                head = conn.execute(
                    text(
                        "SELECT content_hash FROM etf_nav_year WHERE unified_code=:c AND nav_year=2025"
                    ),
                    dict(c=f"{i:06}.SH"),
                ).scalar_one()
                assert head == digest(rows)
            audit_seconds = time.perf_counter() - started
            conn.exec_driver_sql("ANALYZE TABLE " + ",".join(TABLES))
            allocation = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT TABLE_NAME AS table_name,TABLE_ROWS AS estimated_rows,DATA_LENGTH AS data_length,INDEX_LENGTH AS index_length FROM information_schema.tables WHERE table_schema=:db"
                    ),
                    dict(db=session.database),
                ).mappings()
                if r["table_name"] in TABLES
            ]
            plans = {
                k: [dict(r) for r in conn.exec_driver_sql("EXPLAIN " + sql).mappings()]
                for k, sql in {
                    "nav_range": "SELECT * FROM etf_daily_nav WHERE unified_code='000001.SH' AND nav_date BETWEEN '2025-01-01' AND '2025-12-31' ORDER BY nav_date LIMIT 500",
                    "share_day": "SELECT * FROM etf_daily_share WHERE share_date='2025-01-02' AND source='sse' ORDER BY unified_code LIMIT 200",
                    "nav_day": "SELECT * FROM etf_daily_nav WHERE nav_date='2025-01-02' ORDER BY unified_code LIMIT 200",
                }.items()
            }
        measurements.update(
            share_import_seconds=share_seconds,
            nav_import_seconds=nav_seconds,
            allocated_bytes=sum(r["data_length"] + r["index_length"] for r in allocation),
            unit_python_peak_bytes=peak,
            content_audit_seconds=audit_seconds,
        )
        limits = dict(
            nav_year_p95_ms=150,
            share_day_p95_ms=200,
            nav_day_p95_ms=200,
            review_p95_ms=500,
            share_import_seconds=90,
            nav_import_seconds=90,
            allocated_bytes=256 * 1024**2,
            unit_python_peak_bytes=16 * 1024**2,
            content_audit_seconds=60,
        )
        schema_objects = objects(
            (root / "sql/schema.sql").read_text("utf8"),
            json.loads((root / "sql/schema-contract.json").read_text("utf8")),
            json.loads((root / "sql/business-schema.json").read_text("utf8")),
            TABLES,
        )
        session.report.update(
            bindings=session.frozen_inputs,
            feature="etf-fundamentals",
            schema_objects=schema_objects,
            ddl_scopes={k: v["ddl_sha256"] for k, v in schema_objects.items()},
            measurements=measurements,
            limits=limits,
            queries=details,
            explain=plans,
            allocation=allocation,
            message_bytes=dict(
                mean=sum(message_sizes) / len(message_sizes),
                p95=sorted(message_sizes)[int(len(message_sizes) * 0.95) - 1],
                maximum=max(message_sizes),
            ),
            conditions=dict(
                sample="40 complete source days ×2500 ETFs=100000 shares;400 ETFs ×250 dates=100000 NAV facts",
                cache="first query separately;20 warm repeats;buffer pool not flushed;no cold-disk claim",
                memory="tracemalloc normalization of complete units;not process/MySQL RSS",
            ),
            correctness=dict(
                repeat_business_dml=[r["written_count"] for r in repeated],
                revision_business_dml=[r["written_count"] for r in revised],
                all_content_and_keys_audited=True,
            ),
            reviewed_tradeoffs="两类结构化事实和内容证明独立；精确DECIMAL、日期反查索引计入空间。放大20万事实仅证明所测规模；五年空间按实际分配外推，不宣称全历史冷缓存已测。",
        )
        if any(measurements[k] > limit for k, limit in limits.items()):
            raise ValueError(
                "ETF capacity exceeded its declared budget; inspect the retained report"
            )
        session.measurements_complete = True
    print("PASS ETF fundamentals capacity: " + args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--test-mysql", required=True)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
