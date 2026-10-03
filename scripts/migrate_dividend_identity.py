"""Explicit non-destructive dividend key migration; never run on application startup."""
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.data.capital_actions import decode
from empire.plugins.datasets.capital_actions import digest, source_row
from empire.plugins.datasets.capital_archive import CapitalDataset
from empire.plugins.datasets.capital_validation import as_source
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache


def business_snapshot(rows):
    return dict(rows=len(rows), sha256=digest(sorted(
        [digest({k: v for k, v in row.items() if k not in ('record_key', 'content_hash')})
         for row in rows])))


def migrate_rows(engine, namespace, source='tdx'):
    with engine.begin() as conn:
        records = [dict(r) for r in conn.execute(text(
            'SELECT * FROM dividend_plan WHERE source=:source FOR UPDATE'), {'source': source}).mappings()]
        # Snapshot normalized JSON and immutable observation times, independent of keys.
        def snapshot(records):
            values = []
            for row in records:
                item = decode(row)
                item['version_observed_at'] = row['version_observed_at'].isoformat()
                values.append(item)
            return business_snapshot(values)
        before = snapshot(records)
        planned = []
        seen = set()
        for row in records:
            raw, stock = as_source('dividends', decode(row))
            current = source_row('dividends', raw, stock)
            if current['record_key'] in seen:
                raise ValueError('迁移产生重复业务键；事务回滚，不合并或删除记录')
            seen.add(current['record_key'])
            planned.append((row, current))
        changed = 0
        for old, current in planned:
            checksum = digest(current)
            if old['record_key'] != current['record_key'] or old['content_hash'] != checksum:
                conn.execute(text('UPDATE dividend_plan SET record_key=:new_key,content_hash=:hash '
                    'WHERE source=:source AND record_key=:old_key'),
                    dict(new_key=current['record_key'], hash=checksum, source=source, old_key=old['record_key']))
                changed += 1
        after = snapshot([dict(r) for r in conn.execute(text(
            'SELECT * FROM dividend_plan WHERE source=:source'), {'source': source}).mappings()])
        if before != after:
            raise RuntimeError('分红业务内容发生变化；事务回滚')
        old = read_state(conn, namespace, 'tdx-dividends', source, lock=True)
        reset = bool(changed or old.get('contract_version') != 2 or old.get('identity_migration_pending'))
        if reset:
            # Retain SQL observation watermarks to reject late old responses.
            units = {k: {'observed_at': v['observed_at']} for k, v in old.get('units', {}).items()}
            save_state(conn, namespace, 'tdx-dividends', source, 'dividends.unit',
                       dict(contract_version=2, units=units, identity_migration_pending=True), old)
        return dict(before=before, after=after, changed_keys=changed, reset_required=reset)


async def migrate(cfg):
    lock = acquire_instance_lock()
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    namespace = cfg['redis'].get('namespace', 'empire:dev')
    try:
        if await client.xlen(namespace + ':ingest'):
            raise RuntimeError('待归档队列非空，拒绝修改业务键')
        cache = FingerprintCache(SimpleNamespace(client=client, prefix=namespace), cfg.get('archive', {}),
                                 lambda _: CapitalDataset.FINGERPRINT_VERSION)
        await cache.invalidate('dividends', 'tdx')
        report = migrate_rows(engine, namespace)
        if report['reset_required']:
            await client.delete(namespace + ':checkpoint:tdx-dividends-v1',
                                namespace + ':archive:progress:tdx-dividends-v1')
            with engine.begin() as conn:
                old = read_state(conn, namespace, 'tdx-dividends', 'tdx', lock=True)
                current = {k: v for k, v in old.items() if k != 'identity_migration_pending'}
                save_state(conn, namespace, 'tdx-dividends', 'tdx', 'dividends.unit', current, old)
        print(json.dumps(report))
        return report
    finally:
        await client.aclose()
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    config = load_config()
    try:
        asyncio.run(migrate(config))
    except Exception as exc:
        raise SystemExit(redact(exc, config)) from None
