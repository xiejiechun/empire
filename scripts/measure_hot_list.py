"""Typed day/seat capacity in the shared UUID-owned independent SQL harness."""

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
from empire.contracts.preparation_scope import PreparationScope
from empire.core.config import load_config
from empire.features.hot_list.contract import DATASET, JOB, PROJECT, TABLES, digest
from empire.features.hot_list.dataset import HotListDataset
from empire.features.hot_list.query import HotListDataPlugin
from empire.features.hot_list.source import parse_detail
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from scripts.capacity_session import CapacitySession
from tests.test_tdx_hot_list import detail

INPUTS = tuple(
    "src/empire/features/hot_list/" + name + ".py"
    for name in ("contract", "source", "dataset", "query")
) + ("scripts/measure_hot_list.py", "scripts/capacity_session.py", "tests/test_tdx_hot_list.py")


async def run(args):
    root = Path(__file__).resolve().parents[1]
    settings = json.loads(Path(args.test_settings).read_text("utf-8-sig"))
    capacity = CapacitySession(
        load_config()["mysql"],
        settings,
        root=root,
        subject="preview",
        output=args.report,
        input_paths=INPUTS,
    )
    schema = (root / "sql/schema.sql").read_text("utf8")
    targets = (*TABLES, "collection_state", "stock")
    statements = {
        t: re.search(r"CREATE TABLE IF NOT EXISTS " + t + r"\s*\([\s\S]*?;", schema)[0]
        for t in targets
    }
    mapping, fixtures, dml = HotListDataset(), [], []
    dates = [(date(2026, 3, 3) - timedelta(days=i)).isoformat() for i in range(10)]
    value = parse_detail(detail(shenzhen=True))
    for i in range(500):
        code = f"{600000 + i:06d}.SH"
        units = [("directory", "", dict(dates=dates, through="2026-10-23"))]
        units.extend(("detail", d, value) for d in dates)
        units.append(
            (
                "finish",
                "",
                dict(directory_hash=digest(dates), count=len(dates), through="2026-10-23"),
            )
        )
        for mode, stamp, content in units:
            e = make_envelope(
                source="tdx",
                dataset=DATASET,
                schema_version=1,
                job_key=JOB,
                business_key=f"{mode}:{code}:{stamp}",
                batch_id="capacity",
                run_id="capacity",
                payload=dict(
                    page=len(fixtures) + 1, mode=mode, code=code, date=stamp, value=content
                ),
            )
            fixtures.append((e, mapping.normalize(e)))

    def write(conn, e, data):
        code = data["code"]
        prior, exists = read_unit(conn, "capacity", PROJECT, "tdx", code)
        outcome = mapping.write(conn, e, {**data, "archive_state": prior})
        state = mapping.archive_state(e, data, outcome, prior)
        save_unit(conn, "capacity", PROJECT, "tdx", DATASET, code, state, prior, exists)
        return outcome

    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and any(
            t in sql for t in TABLES
        ):
            dml.append(sql)

    with capacity:
        engine = capacity.engine
        with engine.begin() as conn:
            for statement in statements.values():
                conn.exec_driver_sql(statement)
            conn.execute(
                text("INSERT INTO stock(unified_code,name) VALUES(:code,:name)"),
                [dict(code=f"{600000 + i:06d}.SH", name="容量测试") for i in range(500)],
            )
        tracemalloc.start()
        started = time.perf_counter()
        for e, data in fixtures:
            with engine.begin() as conn:
                write(conn, e, data)
        imported = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.listen(engine, "before_cursor_execute", capture)
        started = time.perf_counter()
        for e, data in fixtures:
            with engine.begin() as conn:
                write(conn, e, data)
        repeated = time.perf_counter() - started
        event.remove(engine, "before_cursor_execute", capture)
        query = HotListDataPlugin("capacity")

        async def read(fn, *args):
            return fn(*args)

        query.mysql = SimpleNamespace(read_engine=engine, engine=engine, read=read)
        page_ms, detail_ms, pool_ms, plans = [], [], [], {}
        for i in range(10):
            started = time.perf_counter()
            pool = await query.securities()
            pool_ms.append((time.perf_counter() - started) * 1000)
            if pool != [f"{600000 + n:06d}.SH" for n in range(500)]:
                raise ValueError("股票池集合不一致")
            started = time.perf_counter()
            page = await query.browse()
            page_ms.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            item = await query.detail("600000.SH", dates[0])
            detail_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        audit = query.audit(
            PreparationScope(codes=tuple(f"{600000 + i:06d}" for i in range(200))), True
        )
        audit_ms = (time.perf_counter() - started) * 1000
        if not audit["valid"] or audit["missing"]:
            raise ValueError("放大日期集合审计失败")
        with engine.connect() as conn:
            for label, sql in dict(
                pool="SELECT unified_code FROM stock UNION SELECT DISTINCT unified_code FROM hot_list_day FORCE INDEX (ix_date) ORDER BY unified_code LIMIT 30001",
                page="SELECT unified_code,list_date,detail_status FROM hot_list_day ORDER BY list_date DESC,unified_code DESC LIMIT 200",
                security="SELECT list_date FROM hot_list_day WHERE unified_code='600000.SH' ORDER BY list_date DESC LIMIT 200",
                seat="SELECT seat_name,buy_amount FROM hot_list_seat WHERE unified_code='600000.SH' AND list_date='2026-03-03' ORDER BY seq LIMIT 10001",
                analysis="SELECT reason_code,SUM(turnover) FROM hot_list_reason WHERE reason_code='070001' AND list_date BETWEEN '2026-02-20' AND '2026-03-03' GROUP BY reason_code",
            ).items():
                plans[label] = [dict(r) for r in conn.exec_driver_sql("EXPLAIN " + sql).mappings()]
                plans[label + "_actual_rows"] = len(conn.exec_driver_sql(sql).all())
            conn.exec_driver_sql("ANALYZE TABLE " + ",".join(targets)).all()
            allocation = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT table_name,data_length,index_length FROM information_schema.tables WHERE table_schema=:db"
                    ),
                    dict(db=capacity.database),
                ).mappings()
            ]
            version = conn.exec_driver_sql("SELECT VERSION()").scalar_one()
        allocated = sum(int(r["DATA_LENGTH"]) + int(r["INDEX_LENGTH"]) for r in allocation)
        measured = dict(
            import_seconds=imported,
            repeated_seconds=repeated,
            repeated_business_dml=len(dml),
            day_heads=5000,
            pool_p95_ms=max(pool_ms),
            page_p95_ms=max(page_ms),
            detail_p95_ms=max(detail_ms),
            audit_ms=audit_ms,
            allocated_bytes=allocated,
            peak_python_bytes=peak,
            page_bytes=len(json.dumps(page, default=str).encode()),
            detail_bytes=len(json.dumps(item, default=str).encode()),
        )
        limits = dict(
            import_seconds=60,
            repeated_business_dml=0,
            pool_p95_ms=100,
            page_p95_ms=100,
            detail_p95_ms=100,
            audit_ms=10000,
            allocated_bytes=134217728,
            peak_python_bytes=134217728,
            page_bytes=262144,
            detail_bytes=524288,
        )
        capacity.report.update(
            dataset="hot_list.tdx_unit",
            measurements=measured,
            limits=limits,
            conditions=dict(
                platform=platform.platform(),
                mysql=version,
                synthetic=True,
                securities=500,
                dates_per_stock=10,
                actual_sample="独立30随机股票代理全历史验证另列，不将合成容量当实际数据",
                cache="首次未强制冷缓存，后九次热读，最大值约束P95",
                allocation=allocation,
                transactions="每目录/日期/证券证明独立事务，5000日头、5000原因、15000席位",
                peak="tracemalloc仅跟踪测量阶段Python分配，不代表进程RSS",
            ),
            bindings=capacity.frozen_inputs,
            ddl_scopes={t: hashlib.sha256(statements[t].encode()).hexdigest() for t in TABLES},
            explain=plans,
            reviewed_tradeoffs="三表避免核心事实JSON，auxiliary/extension白名单有界；审计最多2000日期、20日期批读。源无版本的SQL版本为最后内容变化观测，过期摘要后不能证明其后的无变化观察上界。",
            projected_five_year_bytes=allocated * 125000 // 5000,
        )
        if any(measured[k] > bound for k, bound in limits.items()):
            raise ValueError("容量预算超限：" + str(measured))
        capacity.measurements_complete = True
    print("PASS hot-list capacity", measured)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-settings", required=True)
    parser.add_argument("--report", required=True)
    asyncio.run(run(parser.parse_args()))
