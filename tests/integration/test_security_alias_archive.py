"""Explicit complete table through the same Redis/archive path in private schemas."""
import copy
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts import business_schema
from empire.contracts.dataset import DatasetContribution
from empire.core.config import load_config
from empire.features.security_aliases import dataset as security_aliases
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import shape
from tests.test_bse_code_mapping import ROWS, envelope

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private database opt in')]


def scalar(mysql, sql):
    with mysql.read_engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


@pytest.fixture
async def aliases(monkeypatch):
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    engine = make_engine(cfg['mysql'])
    with engine.begin() as conn:
        sql = Path('sql/schema.sql').read_text('utf8')
        ddl = sql[sql.index('CREATE TABLE IF NOT EXISTS security_code_alias ('):].split(';', 1)[0]
        conn.exec_driver_sql(ddl)
    engine.dispose()
    monkeypatch.setattr(business_schema, 'FIXED_SOURCES', {**business_schema.FIXED_SOURCES, 'security_code_alias': 'bse'})
    manager = build_manager(cfg)
    catalog = manager.entries['dataset.astock'].plugin
    if 'bse.code_mapping.complete' not in catalog.datasets:
        manager.entries['dataset.astock'].plugin = DatasetPlugin((*catalog.contributions,
            DatasetContribution(security_aliases, 'incremental', {security_aliases.JOB: security_aliases.PROJECT})))
    try:
        await manager.start('pipeline.ingest')
        ingest = manager.registry.get('ingest.publish')
        archive = manager.registry.get('archive.worker')
        async def publish(event):
            cp = await ingest.checkpoint(event.job_key)
            await ingest.publish_page([event], job_key=event.job_key, expected_revision=cp['revision'], cursor={})
            await archive.flush()
        yield manager, publish
    finally:
        await manager.shutdown()
        redis = create_client(cfg['redis'])
        keys = [key async for key in redis.scan_iter(match=cfg['redis']['namespace'] + ':*')]
        if keys:
            assert all(key.startswith(cfg['redis']['namespace'] + ':') for key in keys)
            await redis.delete(*keys)
        await redis.aclose()


async def test_shared_archive_replay_revisions_stale_and_sets(aliases):
    manager, publish = aliases
    mysql = manager.registry.get('mysql.store')
    archive = manager.registry.get('archive.worker')
    redis = manager.registry.get('redis.store')
    writes = []
    def capture(conn, cursor, sql, params, context, many):
        if 'security_code_alias' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        base = envelope().model_copy(update={'observed_at': datetime.now(UTC) - timedelta(minutes=5)})
        await publish(base)
        assert len(writes) == 1 and await redis.client.xlen(redis.stream) == 0
        writes.clear()
        await publish(base)
        assert not writes and await redis.client.xlen(redis.stream) == 0
        await archive.fingerprints.invalidate(security_aliases.FINGERPRINT_NAMESPACE, 'bse')
        await publish(base)
        assert not writes and await redis.client.xlen(redis.stream) == 0
        revised = [{**ROWS[0], 'name': '旭杰科技修订'}]
        changed = envelope(revised).model_copy(update={'observed_at': base.observed_at + timedelta(seconds=2)})
        await publish(changed)
        assert len(writes) == 1
        writes.clear()
        await publish(base)
        assert not writes and await redis.client.xlen(redis.stream) == 0
        stored = await mysql.read(scalar, mysql, 'SELECT name FROM security_code_alias')
        assert stored == '旭杰科技修订'
        # Same count but another business set adds a second identity, never erases history.
        other = [dict(legacy_code='831010', unified_code='920010.BJ', name='凯添燃气', listing_date='2020-07-27')]
        await publish(envelope(other))
        assert await mysql.read(scalar, mysql, 'SELECT COUNT(*) FROM security_code_alias') == 2
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_capacity_1000_rows(aliases, tmp_path):
    manager, publish = aliases
    rows = [dict(legacy_code=str(830000+i), unified_code=f'920{i:03d}.BJ', name=f'证券{i}', listing_date='2020-07-27') for i in range(1000)]
    started = perf_counter()
    await publish(envelope(rows))
    imported_ms = (perf_counter() - started) * 1000
    mysql = manager.registry.get('mysql.store')
    def measure(conn):
        started = perf_counter()
        stored = conn.execute(text('SELECT legacy_code,unified_code,name,listing_date FROM security_code_alias ORDER BY legacy_code LIMIT 1000')).all()
        read_ms = (perf_counter() - started) * 1000
        plan = conn.exec_driver_sql("EXPLAIN SELECT * FROM security_code_alias WHERE unified_code='920149.BJ'").mappings().all()
        conn.exec_driver_sql('ANALYZE TABLE security_code_alias')
        size = conn.execute(text('SELECT DATA_LENGTH+INDEX_LENGTH FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:t'), {'t':'security_code_alias'}).scalar_one()
        return dict(import_ms=imported_ms, read_ms=read_ms, allocated_bytes=int(size), rows=len(stored),
                    explain=[dict(row) for row in plan], shape=shape(conn, 'security_code_alias'))
    def operation():
        with mysql.engine.connect() as conn:
            return measure(conn)
    report = await mysql.control(operation)
    assert report['rows'] == 1000 and report['allocated_bytes'] <= 1048576
    assert report['read_ms'] <= 100 and report['import_ms'] <= 2000
    assert report['explain'][0]['key'] == 'ux_alias_security'
    (tmp_path / 'capacity.json').write_text(json.dumps(report, indent=2, default=str), 'utf8')


async def test_commit_ack_failure_and_sql_failure_keep_queue(aliases, monkeypatch):
    manager, _ = aliases
    ingest = manager.registry.get('ingest.publish')
    archive = manager.registry.get('archive.worker')
    redis = manager.registry.get('redis.store')
    mysql = manager.registry.get('mysql.store')
    base = envelope().model_copy(update={
        'observed_at': (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=800000)})
    original = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack failed')))
    async with archive.lock:
        checkpoint = await ingest.checkpoint(security_aliases.JOB)
        await ingest.publish_page([base], job_key=security_aliases.JOB,
            expected_revision=checkpoint['revision'], cursor={})
    with pytest.raises(RuntimeError, match='ack failed'):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 1
    assert await mysql.read(scalar, mysql, 'SELECT COUNT(*) FROM security_code_alias') == 1
    monkeypatch.setattr(archive, 'acknowledge', original)
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0
    # A newer response within the same second must survive a cold SQL replay,
    # even when MySQL would round the earlier timestamp up without truncation.
    await archive.fingerprints.invalidate(security_aliases.FINGERPRINT_NAMESPACE, 'bse')
    changed = envelope([{**ROWS[0], 'name': '修订'}]).model_copy(update={
        'observed_at': base.observed_at + timedelta(microseconds=100000)})
    writer = security_aliases.write
    monkeypatch.setattr(security_aliases, 'write', lambda *args: (_ for _ in ()).throw(RuntimeError('SQL unavailable')))
    async with archive.lock:
        checkpoint = await ingest.checkpoint(security_aliases.JOB)
        await ingest.publish_page([changed], job_key=security_aliases.JOB,
            expected_revision=checkpoint['revision'], cursor={})
    with pytest.raises(RuntimeError, match='SQL unavailable'):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 1
    assert await mysql.read(scalar, mysql, 'SELECT name FROM security_code_alias') == '旭杰科技'
    monkeypatch.setattr(security_aliases, 'write', writer)
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0
    assert await mysql.read(scalar, mysql, 'SELECT name FROM security_code_alias') == '修订'
