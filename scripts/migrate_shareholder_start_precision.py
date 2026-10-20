"""Explicit DATE→exact source day/month precision; preserve all stored facts."""
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes


async def run():
    cfg, lock = load_config(), acquire_instance_lock()
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    prefix = cfg['redis'].get('namespace', 'empire')
    report = dict(project='tdx-shareholder-changes', applied=False)
    try:
        if await redis.xlen(prefix + ':ingest'):
            raise ValueError('待归档队列非空，拒绝维护')
        with engine.connect() as conn:
            if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('并发结构维护')
            try:
                def snapshot():
                    checksum, count = hashlib.sha256(), 0
                    for row in conn.execution_options(stream_results=True).exec_driver_sql('SELECT * FROM shareholder_change ORDER BY record_key').mappings():
                        checksum.update(json.dumps(dict(row), sort_keys=True, default=str).encode())
                        count += 1
                    return count, checksum.hexdigest()
                before = snapshot()
                column = conn.exec_driver_sql("SHOW COLUMNS FROM shareholder_change LIKE 'change_start'").mappings().one()
                if column['Type'] == 'date':
                    conn.exec_driver_sql('ALTER TABLE shareholder_change DROP CHECK ck_change_dates, '
                        'MODIFY change_start VARCHAR(10) NULL, ADD CONSTRAINT ck_change_dates CHECK '
                        "(change_start IS NULL OR (change_start REGEXP '^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$' AND change_start<=CAST(change_end AS CHAR) COLLATE utf8mb4_unicode_ci))")
                    conn.commit()
                elif column['Type'] != 'varchar(10)':
                    raise ValueError('未知开始日期结构，拒绝转换')
                quantity = conn.exec_driver_sql("SHOW COLUMNS FROM shareholder_change LIKE 'shares_changed'").mappings().one()
                if quantity['Null'] == 'NO':
                    conn.exec_driver_sql('ALTER TABLE shareholder_change MODIFY shares_changed DECIMAL(28,8) NULL')
                    conn.commit()
                validate_shapes(conn, ['shareholder_change'])
                after = snapshot()
                if before != after:
                    raise ValueError('原业务数量或摘要改变')
                report.update(before=list(before), after=list(after), applied=True)
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        # The transport values for previously accepted full dates are unchanged.
        # Explicitly invalidate current source proofs before full revalidation.
        from types import SimpleNamespace

        from empire.features.performance.dataset import PerformanceDataset
        from empire.plugins.pipeline.fingerprints import FingerprintCache
        store = SimpleNamespace(client=redis, prefix=prefix)
        await FingerprintCache(store, cfg.get('archive', {}), lambda _: PerformanceDataset('shareholder_changes').FINGERPRINT_VERSION).invalidate('tdx_shareholder_changes', 'tdx')
        with engine.begin() as conn:
            conn.execute(text("UPDATE collection_state SET payload=JSON_REMOVE(payload,'$.units','$.manifest') WHERE namespace=:ns AND project_id='tdx-shareholder-changes'"), {'ns': prefix})
        report['proofs_invalidated'] = True
        Path('docs/evidence/shareholder-start-precision-migration-2026-10-13.json').write_text(json.dumps(report, indent=2)+'\n', 'utf8')
        print(json.dumps(report))
    finally:
        engine.dispose()
        await redis.aclose()
        lock.unlock()


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as exc:
        raise SystemExit(redact(exc, load_config())) from None
