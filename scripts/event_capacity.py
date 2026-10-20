"""Owned capacity lifecycle for the two existing complete-market event protocols."""

import asyncio
import hashlib
import importlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, read_server_uuid, test_settings
from source_verification import require
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import make_envelope
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.sql_lane import settle


def protocol(family):
    require(family in ("name_changes", "st_events"), "未知事件容量协议")
    st = family == "st_events"
    kind, column, table = (
        ("implementation", "event_kind", "security_st_event")
        if st
        else ("security", "name_kind", "security_name_change")
    )
    fields = (
        "unified_code,event_date,old_name,new_name,source_occurrences,csrc_industry,tdx_industry"
    )
    security = "unified_code,event_date,old_name,new_name,csrc_industry,tdx_industry"
    end = "2026-10-11" if st else "2026-10-05"
    queries = dict(
        page=f"SELECT {fields} FROM {table} WHERE {column}='{kind}' ORDER BY event_date,unified_code,record_key LIMIT 200",
        security=f"SELECT {security} FROM {table} WHERE {column}='{kind}' AND unified_code='000001.SH' AND event_date BETWEEN '2020-01-01' AND '{end}' ORDER BY event_date,record_key LIMIT 200",
        coverage=f"SELECT {fields} FROM {table} WHERE {column}='{kind}' ORDER BY record_key LIMIT 30001",
    )
    contract = importlib.import_module("empire.features." + family + ".contract")
    dataset = importlib.import_module("empire.features." + family + ".dataset")
    return dict(
        family=family,
        kind=kind,
        table=table,
        column=column,
        queries=queries,
        contract=contract,
        dataset=dataset,
        cls=dataset.StDataset if st else dataset.NameDataset,
    )


class EventCapacityStorage(PrivateStorage):
    def __init__(self, *args, protocol, **kwargs):
        self.protocol = protocol
        super().__init__(*args, **kwargs)

    def guard(self, conn, cursor, statement, parameters, context, executemany):
        approved = {
            "ANALYZE TABLE " + self.protocol["table"],
            *("EXPLAIN " + sql for sql in self.protocol["queries"].values()),
        }
        if statement in approved and not parameters and not executemany:
            super().guard(conn, cursor, "SELECT 1", (), context, False)
            return
        super().guard(conn, cursor, statement, parameters, context, executemany)


def fixed_rows(p):
    rows = [
        [
            f"{i % 5000:06d}.SH",
            (date(2020, 1, 1) + timedelta(days=i // 5000)).isoformat(),
            "原名称" + str(i // 5000),
            "新名称" + str(i // 5000),
            1,
            "证监会行业" + str(i % 100),
            "通达信行业" + str(i % 200),
        ]
        + (["实施其他风险警示；原因" + str(i % 50)] if p["family"] == "st_events" else [])
        for i in range(25000)
    ]
    return sorted(rows, key=p["contract"].identity)


def measure(storage):
    p, root = storage.protocol, project_root()
    engine = make_engine(storage.settings)
    try:
        c, mapping, now = p["contract"], p["cls"](p["kind"]), datetime.now(UTC)
        rows = fixed_rows(p)
        batch = uuid4().hex
        e = make_envelope(
            source="tdx",
            dataset=next(iter(mapping.DATASETS)),
            business_key="SH",
            job_key=mapping.JOB,
            batch_id=batch,
            run_id=batch,
            schema_version=c.SCHEMA_VERSION,
            payload=dict(
                page=1,
                market="SH",
                through=now.date().isoformat(),
                **c.pack_rows(rows),
                source_count=len(rows),
            ),
        )
        data = {**mapping.normalize(e), "archive_state": {}}
        tracemalloc.start()
        started = time.perf_counter()
        with engine.begin() as conn:
            initial = mapping.write(conn, e, data)
        import_seconds = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        with engine.begin() as conn:
            repeat = mapping.write(conn, e, data)
        revised = [list(r) for r in rows]
        revised[0][3] += "修订"
        revised.sort(key=c.identity)
        with engine.begin() as conn:
            revision = mapping.write(conn, e, {**data, "rows": revised})
        timings, samples, explain, actual = {}, {}, {}, {}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar_one()
            conn.exec_driver_sql("ANALYZE TABLE " + p["table"])
            for name, sql in p["queries"].items():
                raw = []
                for _ in range(20):
                    started = time.perf_counter()
                    result = conn.exec_driver_sql(sql).all()
                    raw.append((time.perf_counter() - started) * 1000)
                samples[name], timings[name] = raw, sorted(raw)[18]
                actual[name] = dict(
                    returned=len(result),
                    read_bytes=len(
                        json.dumps(
                            [list(r) for r in result], ensure_ascii=False, default=str
                        ).encode()
                    ),
                )
                explain[name] = [dict(r) for r in conn.exec_driver_sql("EXPLAIN " + sql).mappings()]
            allocation = conn.execute(
                text(
                    "SELECT data_length+index_length FROM information_schema.tables "
                    "WHERE table_schema=:db AND table_name=:object_name"
                ),
                dict(db=storage.database, object_name=p["table"]),
            ).scalar_one()
            stored = p["dataset"].read_rows(conn, p["kind"])
        require(stored == revised, "容量25000事件完整业务集合或内容不同")
        require(
            initial["written_count"] == 25000
            and repeat["written_count"] == 0
            and revision["written_count"] == 2,
            "容量初始/重复/单条修订DML不符",
        )
        family = p["family"]
        bindings = [
            f"src/empire/features/{family}/{n}.py" for n in ("contract", "dataset", "query")
        ]
        bindings += [
            f"scripts/measure_{family}.py",
            "scripts/event_capacity.py",
            "scripts/source_test_storage.py",
            "scripts/source_verification.py",
            "sql/business-schema.json",
            "src/empire/contracts/business_schema.py",
        ]
        ddl = re.search(
            r"CREATE TABLE IF NOT EXISTS " + p["table"] + r"\s*\([\s\S]*?;",
            (root / "sql/schema.sql").read_text("utf-8"),
        ).group()
        return dict(
            bindings={s: hashlib.sha256((root / s).read_bytes()).hexdigest() for s in bindings},
            ddl_scopes={p["table"]: hashlib.sha256(ddl.encode()).hexdigest()},
            measurements=dict(
                page_p95_ms=timings["page"],
                security_p95_ms=timings["security"],
                coverage_p95_ms=timings["coverage"],
                import_seconds=import_seconds,
                allocated_bytes=int(allocation),
            ),
            limits=dict(
                page_p95_ms=50,
                security_p95_ms=50,
                coverage_p95_ms=500,
                import_seconds=10,
                allocated_bytes=128 * 1024**2,
            ),
            conditions=dict(
                platform=platform.platform(),
                mysql=version,
                rows=25000,
                synthetic=True,
                protocol="unchanged 25000 fixed rows, direct dataset SQL write/repeat/revision; original SQL and 20 repetitions",
                cache="first query unforced; subsequent hot repetitions",
                pipeline_scope="SQL capacity only; separate source verification covers full pipeline",
            ),
            reviewed_tradeoffs="紧凑结构化事件与索引；覆盖检查本类型至30000上限，页面200行。保持原25000样本/SQL/阈值。合成容量不宣称能一次入队或生产吞吐；超消息预算仍明确失败。",
            samples=samples,
            explain=explain,
            queries=actual,
            sql=p["queries"],
            python_peak_bytes=peak,
            initial=initial,
            repeat=repeat,
            revision=revision,
            correctness=dict(
                all_rows_equal=True, row_count=len(stored), content_digest=c.digest(stored)
            ),
        )
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


async def verify(args, family):
    output, report = verification.initial_report(args)
    storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, "timeout须为1～7200秒")
        require(
            args.random_count == 0 and args.seed is None and not args.codes,
            "合成容量不能声明随机实采",
        )
        paths = [
            Path(args.pool_config or default_config_path()).resolve(),
            Path(args.test_mysql_settings).resolve(),
        ]
        report["input_files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text("utf-8"))
        require(isinstance(raw, dict), "测试配置须为JSON对象")
        redactor = Redactor(
            [cfg["mysql"].get("password"), cfg["redis"].get("password"), raw.get("password")]
        )
        settings = test_settings(raw)
        p = protocol(family)
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg["mysql"])
        report.update(
            subject=family + "_capacity",
            source_sha256=source_digest(project_root()),
            source_server_uuid=source_uuid,
            acceptance_complete=False,
            sample_30_applicable=False,
            sample_30_reason="25000事件合成SQL容量；不请求来源",
        )
        storage = EventCapacityStorage(
            settings, cfg["redis"], report["run_id"], token_hex(32), source_uuid, protocol=p
        )
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name + ".ownership.json")
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(
            before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1]))
        )
        report["storage"] = storage.identity()
        report["environment"] = dict(
            storage.conn.exec_driver_sql(
                "SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,"
                "@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,@@sync_binlog AS sync_binlog,@@log_bin AS log_bin"
            )
            .mappings()
            .one()
        )
        await storage.create_redis()
        storage.seed([], [])
        async with asyncio.timeout(args.timeout):
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure, storage)))
        report.update(measured)
        report["input_files"].update(
            {str(project_root() / p): sha for p, sha in measured["bindings"].items()}
        )
        require(source_digest(project_root()) == report["source_sha256"], "测量期间源码改变")
        require(
            all(measured["measurements"][k] <= v for k, v in measured["limits"].items()),
            "容量超出冻结原预算",
        )
        require(await storage.client.get(storage.owner_key) == storage.owner, "Redis归属变化")
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report["errors"].append(
            dict(stage="capacity", message=redactor.text(exc, 2048), type=type(exc).__name__)
        )
    finally:
        passed = await verification.complete(output, report, redactor, None, storage, lock, False)
    return passed


def main(family, argv=None):
    parser = verification.parser(__doc__)
    parser.add_argument(
        "--test-settings",
        dest="test_mysql_settings",
        help="显式13348 JSON；与--test-mysql-settings同一入口",
    )
    parser.set_defaults(random_count=0, timeout=900)
    # Required validation is shared; support the established explicit capacity spelling.
    values = list(sys.argv[1:] if argv is None else argv)
    values = ["--test-mysql-settings" if x == "--test-settings" else x for x in values]
    args = parser.parse_args(values)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args, family))
    print(("CLEANUP COMPLETE" if args.cleanup_only else "PASS") if passed else "FAIL", flush=True)
    return 0 if passed else 1
