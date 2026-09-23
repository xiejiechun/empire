"""Explicit one-time maintenance; never called by application startup or upgrades."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root, redact
from empire.plugins.infra.mysql_store import initialize_database, make_engine
from empire.plugins.infra.redis_store import create_client

OLD_TABLES = {
    "stock_universe_member", "stock_universe_page", "stock_universe_batch",
    "ingest_event", "ingest_quarantine",
}
BUSINESS_COLUMNS = "source,node,unified_code,code,name,market,source_symbol"


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


async def check_queue(cfg):
    client = create_client(cfg["redis"])
    prefix = cfg["redis"].get("namespace", "empire:dev")
    try:
        if await client.xlen(f"{prefix}:ingest"):
            raise RuntimeError("待归档队列非空；须先用兼容版本归档，禁止删除有效待归档数据")
        control = json.loads(await client.get(f"{prefix}:collection:control:v1") or "{}")
        if any(job.get("active") for job in control.get("jobs", {}).values()):
            raise RuntimeError("存在待恢复的采集运行；须先完成或正常暂停该运行")
    finally:
        await client.aclose()


def convert(cfg):
    asyncio.run(check_queue(cfg))
    engine = make_engine(cfg["mysql"])
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            if tables == {"stock"}:
                return {"status": "already_applied", "tables": ["stock"]}
            if not OLD_TABLES <= tables or tables - (OLD_TABLES | {"stock"}):
                raise RuntimeError("数据库结构与本次明确的五表简化不匹配；停止处理")
            batches = conn.execute(text("SELECT * FROM stock_universe_batch")).mappings().all()
            if (not batches or any(b["status"] != "complete" for b in batches)
                    or len({(b["source"], b["node"]) for b in batches}) != len(batches)):
                raise RuntimeError("需要每来源恰好一份完整列表；先处理未完成或重复批次")
            if conn.execute(text("SELECT COUNT(*) FROM ingest_quarantine")).scalar_one():
                raise RuntimeError("存在旧错误记录；须先转入 Redis 错误列表，不得丢弃")
            if conn.execute(text("SELECT COUNT(*) FROM ingest_event WHERE dataset NOT LIKE 'stock.universe.%'" )).scalar_one():
                raise RuntimeError("存在其他业务原始事件；本脚本不处理这些数据")
            expected = sum(b["row_count"] for b in batches)
            if any(b["row_count"] != b["expected_count"] or b["row_count"] <= 0 for b in batches):
                raise RuntimeError("原列表数量校验不通过")
            original = [dict(row) for row in conn.execute(text("""
                SELECT b.source,b.node,m.unified_code,m.code,m.name,m.market,m.source_symbol
                FROM stock_universe_member m JOIN stock_universe_batch b USING(snapshot_id)
                ORDER BY b.source,m.unified_code
            """)).mappings()]
            if len(original) != expected:
                raise RuntimeError("原股票成员数量与完整批次不一致")
        initialize_database(cfg["mysql"])
        with engine.begin() as conn:
            existing = [dict(row) for row in conn.execute(text(
                f"SELECT {BUSINESS_COLUMNS} FROM stock ORDER BY source,unified_code"
            )).mappings()]
            if existing and existing != original:
                raise RuntimeError("stock 已有不同的业务数据，禁止覆盖")
            if not existing:
                conn.execute(text("""
                    INSERT INTO stock (source,node,unified_code,code,name,market,source_symbol,
                                       generation,started_at,updated_at)
                    SELECT b.source,b.node,m.unified_code,m.code,m.name,m.market,m.source_symbol,
                           b.snapshot_id,b.started_at,b.finished_at
                    FROM stock_universe_member m JOIN stock_universe_batch b USING(snapshot_id)
                """))
            current = [dict(row) for row in conn.execute(text(
                f"SELECT {BUSINESS_COLUMNS} FROM stock ORDER BY source,unified_code"
            )).mappings()]
            if current != original:
                raise RuntimeError("转换前后股票内容不一致，事务回滚")
        # DDL auto-commits in MySQL: only remove obsolete tables after verified business commit.
        with engine.connect() as conn:
            for table in ("stock_universe_member", "stock_universe_page", "stock_universe_batch",
                          "ingest_event", "ingest_quarantine"):
                conn.execute(text(f"DROP TABLE {table}"))
            conn.commit()
            final_tables = inspect(conn).get_table_names()
            final_rows = [dict(row) for row in conn.execute(text(
                f"SELECT {BUSINESS_COLUMNS} FROM stock ORDER BY source,unified_code"
            )).mappings()]
        if final_rows != original or final_tables != ["stock"]:
            raise RuntimeError("最终验证未通过，请保留现有业务数据检查")
        return {"status": "applied", "at": datetime.now(UTC).isoformat(),
                "tables": final_tables, "stocks_before": len(original), "stocks_after": len(final_rows),
                "business_sha256_before": digest(original), "business_sha256_after": digest(final_rows),
                "queue_before": 0, "old_errors": 0,
                "redis_checkpoints_and_settings": "preserved"}
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="显式将已核对的旧股票五表简化为 stock；应用不会自动调用")
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    assert args.apply
    cfg = load_config()
    lock = acquire_instance_lock()
    try:
        result = convert(cfg)
        path = project_root() / "artifacts" / "storage-cutover.json"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None
    finally:
        lock.unlock()


if __name__ == "__main__":
    main()
