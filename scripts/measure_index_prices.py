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

from capacity_session import CapacitySession
from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.core.config import load_config, project_root
from empire.features.index_prices import dataset as index_prices
from empire.features.index_prices.contract import JOB
from empire.features.index_prices.query import IndexPriceDataPlugin
from empire.features.indices.contract import digest
from empire.plugins.infra.mysql_store import initialize_database


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text("utf8"))
    paths = ['src/empire/features/index_prices/contract.py', 'src/empire/features/index_prices/dataset.py', 'src/empire/features/index_prices/query.py', 'src/empire/features/indices/contract.py', 'scripts/capacity_session.py', 'src/empire/contracts/security.py', 'src/empire/contracts/business_schema.py', 'sql/business-schema.json', 'src/empire/plugins/infra/mysql_store.py', 'src/empire/plugins/infra/collection_state.py', 'sql/schema.sql', 'sql/schema-contract.json', 'scripts/measure_index_prices.py']
    session = CapacitySession(load_config()['mysql'], settings, root=root, subject='index-prices',
                              output=args.output, input_paths=paths)
    with session:
        initialize_database(session.settings)
        engine, database = session.engine, session.database
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
        measurements = {'query_samples_ms': {}}
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
            measurements["query_samples_ms"][name] = values
        with engine.connect() as conn:
            # Verify all 1000 complete years outside the original query timings.
            heads = conn.exec_driver_sql('SELECT index_code,quote_year,row_count,content_hash,complete '
                                         'FROM index_price_year ORDER BY index_code,quote_year').mappings().all()
            assert [h['index_code'] for h in heads] == [f'{i:06d}' for i in range(1000)]
            for head in heads:
                values = index_prices.sql_rows(conn, head['index_code'], 2025)
                expected = revision if head['index_code'] == '000000' else rows
                assert values == expected and head['quote_year'] == 2025 and head['row_count'] == 100
                assert head['content_hash'] == digest(expected) and head['complete']
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
        schema = (root / "sql/schema.sql").read_text("utf8")
        report = dict(
            bindings=dict(session.frozen_inputs),
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
            cleanup_protocol="CapacitySession owned database; final result only after cleanup",
        )
        report['protocol'] = dict(schema=1, preserved_scale=True, preserved_limits=True)
        report['correctness'] = dict(full_business_keys_and_content=True, original_year_digest=digest(rows),
            revised_year_digest=digest(revision), repeat_zero_business_dml=repeat['written_count'] == 0,
            revision_writes=revised['written_count'])
        session.report.update(report)
        if not all(measurements[k] <= limit for k, limit in report['limits'].items()):
            raise RuntimeError('容量预算未通过')
        session.measurements_complete = True
    print(json.dumps(dict(passed=session.report['passed'], measurements=measurements)))



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-settings", required=True)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
