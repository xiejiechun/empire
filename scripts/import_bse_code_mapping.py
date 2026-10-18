"""Explicit BSE mapping import; shared download, ingestion and archive, no scheduling."""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.collectors.bse_code_mapping_source import URL, parse
from empire.plugins.datasets.security_aliases import JOB, PROJECT
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    manager = build_manager(cfg)
    counts = {}
    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts))
    try:
        await manager.start('infra.http')
        http = manager.registry.get('http.fetch')
        observed = datetime.now(UTC)
        response = await http.request('GET', URL, allowed_domains=('bse.cn',), project_id=PROJECT,
            policy=http.response_policy('generic'), max_retries=2, max_redirects=0,
            headers={'Accept': 'text/html,*/*', 'Origin': 'https://www.bse.cn',
                     'Referer': 'https://www.bse.cn/', 'User-Agent': 'Mozilla/5.0'})
        try:
            rows = parse(response.content)
            report = dict(source_count=len(rows), source_url=URL, response_sha256=hashlib.sha256(response.content).hexdigest(),
                network=counts, policy=dict(use_proxy=True, proxy_fallback=True), applied=False)
        finally:
            response.close()
        if args.apply:
            await manager.start('pipeline.ingest')
            ingest = manager.registry.get('ingest.publish')
            redis = manager.registry.get('redis.store')
            if await redis.client.xlen(redis.stream):
                raise RuntimeError('已有待归档消息，先由原正式归档器完成后再导入')
            run_id = uuid4().hex
            event = make_envelope(source='bse', dataset='bse.code_mapping.complete', business_key='official-table',
                job_key=JOB, run_id=run_id, batch_id=run_id,
                payload=dict(page=1, rows=rows, source_count=len(rows), source_url=URL)).model_copy(update={'observed_at': observed})
            checkpoint = await ingest.checkpoint(JOB)
            await ingest.publish_page([event], job_key=JOB, expected_revision=checkpoint['revision'], cursor=dict(batch_id=run_id, page=1))
            async with asyncio.timeout(120):
                while await redis.client.xlen(redis.stream):
                    await asyncio.sleep(0.1)
            mysql = manager.registry.get('mysql.store')
            def query():
                with mysql.read_engine.connect() as conn:
                    stored = [dict(row) for row in conn.execute(text(
                        'SELECT legacy_code,unified_code,name,listing_date FROM security_code_alias ORDER BY legacy_code LIMIT 1000')).mappings()]
                for row in stored:
                    row['listing_date'] = row['listing_date'].isoformat()
                return stored
            stored = await mysql.read(query)
            index = {row['legacy_code']: row for row in stored}
            if any(index.get(row['legacy_code']) != row for row in rows):
                raise RuntimeError('来源到正式SQL映射集合或字段核对失败')
            report.update(applied=True, sql_count=len(stored), source_sql_equal=True, pending_stream=0,
                          example=index.get('836149'), business_set_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
