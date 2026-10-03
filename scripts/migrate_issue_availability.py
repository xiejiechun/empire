"""Upgrade explicit detail availability without modifying existing business data."""
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.business_schema import require_fixed_source
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.data.capital_actions import decode
from empire.plugins.datasets.capital_actions import digest, ordered, unit_key, validate_rows
from empire.plugins.datasets.capital_archive import CapitalDataset
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache


def snapshot(conn, source):
    require_fixed_source('additional_issue', source)
    rows = [dict(row) for row in conn.execute(text(
        'SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code FROM additional_issue WHERE TRUE ORDER BY record_key'),
        {'source': source}).mappings()]
    if len(rows) > 10000:
        raise ValueError('增发维护范围超过安全上限')
    return {'count': len(rows), 'sha256': digest(json.loads(json.dumps(rows, default=str)))}, rows


def migrate_rows(engine, namespace, source='tdx'):
    require_fixed_source('additional_issue', source)
    with engine.begin() as conn:
        before, _ = snapshot(conn, source)
        old = read_state(conn, namespace, 'tdx-additional-issues', source, lock=True)
        reset = old.get('contract_version') != 3 or bool(old.get('detail_migration_pending'))
        if reset:
            units = {key: {'observed_at': value['observed_at']} for key, value in old.get('units', {}).items()}
            save_state(conn, namespace, 'tdx-additional-issues', source, 'additional_issues',
                dict(contract_version=3, units=units, detail_migration_pending=True), old)
        after, _ = snapshot(conn, source)
        if before != after:
            raise RuntimeError('增发业务内容改变，维护回滚')
        return {'before': before, 'after': after, 'reset_required': reset}


async def migrate(cfg):
    lock = acquire_instance_lock()
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    namespace = cfg['redis'].get('namespace', 'empire:dev')
    try:
        if await client.xlen(namespace + ':ingest'):
            raise RuntimeError('待归档队列非空，拒绝维护')
        with engine.connect() as conn:
            _, raw = snapshot(conn, 'tdx')
        cache = FingerprintCache(SimpleNamespace(client=client, prefix=namespace), cfg.get('archive', {}),
                                 lambda _: CapitalDataset.FINGERPRINT_VERSION)
        groups = {}
        for value in raw:
            row = decode(value)
            groups.setdefault(unit_key(row), []).append(row)
        proofs = await cache.peek('additional_issues', 'tdx', list(groups))
        affected = ['manifest']
        retained = 0
        for unit, rows in groups.items():
            rows = ordered(rows)
            try:
                validate_rows('additional_issues', unit, rows)
                valid = proofs.get(unit, {}).get('hash') == digest({'rows': rows, 'manifest': None})
            except (KeyError, ValueError, TypeError, ArithmeticError):
                valid = False
            if valid:
                retained += 1
            else:
                affected.append(unit)
        report = migrate_rows(engine, namespace)
        if report['reset_required']:
            await cache.invalidate_entries('additional_issues', 'tdx', affected)
            await client.delete(namespace + ':checkpoint:tdx-additional-issues-v1',
                                namespace + ':archive:progress:tdx-additional-issues-v1')
            with engine.begin() as conn:
                old = read_state(conn, namespace, 'tdx-additional-issues', 'tdx', lock=True)
                save_state(conn, namespace, 'tdx-additional-issues', 'tdx', 'additional_issues',
                           {key: value for key, value in old.items() if key != 'detail_migration_pending'}, old)
        report['unchanged_unit_fingerprints_retained'] = retained
        with engine.connect() as conn:
            after, _ = snapshot(conn, 'tdx')
        assert report['before'] == after
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
