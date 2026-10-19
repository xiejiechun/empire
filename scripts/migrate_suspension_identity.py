"""Historical pre-v1 maintenance only; not the current business-v2 upgrade entrance. Explicit, non-destructive source-record identity migration; Empire must be closed."""
import asyncio
import hashlib
import json
import re
from types import SimpleNamespace

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.suspensions.contract import FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache

FIELDS = 'source,market,code,name,suspended_at,resumed_at,suspension_type,source_note,reason,version_observed_at'


def snapshot(engine, table):
    digest, count = hashlib.sha256(), 0
    with engine.connect() as conn:
        for row in conn.execute(text(f'SELECT {FIELDS} FROM {table} ORDER BY '
                                     'source,market,code,suspended_at,resumed_at,source_note,reason,name')):
            digest.update(json.dumps(list(row), ensure_ascii=False, default=str).encode())
            count += 1
    return {'rows': count, 'sha256': digest.hexdigest()}


def migrate_schema(engine, table='suspension_event'):
    if table != 'suspension_event' and not re.fullmatch(r'test_suspension_[a-f0-9]{32}', table):
        raise ValueError('Invalid maintenance table')
    before = snapshot(engine, table)
    columns = {column['name'] for column in inspect(engine).get_columns(table)}
    primary = inspect(engine).get_pk_constraint(table)['constrained_columns']
    resume_identity = ['source', 'market', 'code', 'suspended_at', 'resume_key']
    expected = [*resume_identity, 'record_key']
    if primary not in (expected, resume_identity, resume_identity[:-1]):
        raise RuntimeError('Unexpected suspension primary key; no changes made')
    with engine.begin() as conn:
        if 'source_dates' not in columns:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN source_dates JSON NULL'))
        if 'resume_key' not in columns:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN resume_key DATETIME(6) NOT NULL DEFAULT '1000-01-01 00:00:00'"))
        if 'record_key' not in columns:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN record_key CHAR(64) CHARACTER SET ascii "
                              "COLLATE ascii_bin NOT NULL DEFAULT " + "'" + "0" * 64 + "'"))
        conn.execute(text(f"UPDATE {table} SET resume_key=COALESCE(resumed_at,'1000-01-01 00:00:00') "
                          "WHERE resume_key<>COALESCE(resumed_at,'1000-01-01 00:00:00')"))
        conn.execute(text(f"UPDATE {table} SET record_key=SHA2(CONCAT(CHAR_LENGTH(source_note),':',"
                          "source_note,CHAR_LENGTH(reason),':',reason),256) WHERE record_key<>"
                          "SHA2(CONCAT(CHAR_LENGTH(source_note),':',source_note,CHAR_LENGTH(reason),':',reason),256)"))
        if primary != expected:
            conn.execute(text(f'ALTER TABLE {table} DROP PRIMARY KEY, ADD PRIMARY KEY '
                              '(source,market,code,suspended_at,resume_key,record_key)'))
        constraints = inspect(conn).get_check_constraints(table)
        if not any('resume_key' in check['sqltext'] for check in constraints):
            conn.execute(text(f"ALTER TABLE {table} ADD CHECK (resume_key=COALESCE(resumed_at,'1000-01-01 00:00:00'))"))
        conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN resume_key DROP DEFAULT'))
        conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN record_key DROP DEFAULT'))
    after = snapshot(engine, table)
    if before != after:
        raise RuntimeError('Business count/digest changed; stop before restarting Empire')
    return {'before': before, 'after': after, 'business_unchanged': True}


async def migrate(cfg):
    lock = acquire_instance_lock()
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    namespace = cfg['redis'].get('namespace', 'empire:dev')
    try:
        if await client.xlen(namespace+':ingest'):
            raise RuntimeError('Pending archive queue is not empty; migration refused')
        cache = FingerprintCache(SimpleNamespace(client=client, prefix=namespace), cfg.get('archive', {}),
                                 lambda _: FINGERPRINT_VERSION)
        await cache.invalidate('suspensions', 'tdx')
        report = migrate_schema(engine)
        with engine.begin() as conn:
            old = read_state(conn, namespace, 'tdx-suspensions', 'tdx', lock=True)
            reset = (old.get('record_identity') != 'source-record-v3'
                     or old.get('source_calendar_version') != 1 or old.get('collection_integrity_version') != 2
                     or old.get('identity_migration_pending', False))
            if reset:
                save_state(conn, namespace, 'tdx-suspensions', 'tdx', 'suspensions',
                           {'record_identity': 'source-record-v3', 'source_calendar_version': 1, 'collection_integrity_version': 2,
                            'identity_migration_pending': True}, old)
        if reset:
            await client.delete(namespace+':checkpoint:tdx-suspensions-v1',
                                namespace+':archive:progress:tdx-suspensions-v1')
            with engine.begin() as conn:
                old = read_state(conn, namespace, 'tdx-suspensions', 'tdx', lock=True)
                save_state(conn, namespace, 'tdx-suspensions', 'tdx', 'suspensions',
                           {'record_identity': 'source-record-v3', 'source_calendar_version': 1,
                            'collection_integrity_version': 2}, old)
        report['historical_recheck_required'] = reset
        print(json.dumps(report))
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
