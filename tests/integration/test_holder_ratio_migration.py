"""Exact CHECK-only migration preserves existing facts and can safely resume."""
import json
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.holders.contract import KINDS
from empire.features.holders.dataset import HolderDataset
from empire.features.holders.source import parse
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from scripts import migrate_holder_ratio as migration
from tests.test_ths_holders import STOCK, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Owned storage')]


async def test_exact_constraint_upgrade_preserves_records_and_reentry(monkeypatch, tmp_path):
    cfg = load_config()
    monkeypatch.setattr(migration, 'load_config', lambda _: cfg)
    monkeypatch.setattr('empire.__main__.user_data_dir', lambda: tmp_path)
    engine = make_engine(cfg['mysql'])
    mapping = HolderDataset()
    rows = {kind: parse(source(), kind, STOCK) for kind in KINDS}
    e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=mapping.JOB,
        business_key=STOCK['unified_code'], run_id='test', batch_id='test',
        payload=dict(page=1, unit=STOCK['unified_code'], reports=rows, manifest=None, gaps=[]))
    try:
        with engine.begin() as conn:
            mapping.write(conn, e, {**mapping.normalize(e), 'archive_state': {}})
        with engine.connect() as conn:
            for table, (check, new, old) in migration.CHANGES.items():
                declaration = next(line.strip().rstrip(',') for line in migration.ddl(table).splitlines() if 'CONSTRAINT ' + check + ' ' in line)
                declaration = declaration.replace('0 AND 511', '0 AND 255').replace('ratio BETWEEN 0 AND 99999.9999', 'ratio BETWEEN 0 AND 100')
                conn.exec_driver_sql(f'ALTER TABLE {table} DROP CHECK {check}, ADD ' + declaration)
                conn.commit()
        args = SimpleNamespace(config=None, apply=True, report=str(tmp_path / 'migration.json'))
        writes = []
        from sqlalchemy.engine import Engine
        def capture(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(Engine, 'before_cursor_execute', capture)
        try:
            first = await migration.run(args)
            second = await migration.run(args)
        finally:
            event.remove(Engine, 'before_cursor_execute', capture)
        assert first['before'] == first['after'] and first['before']['reports'] == 3
        assert len(first['changes']) == 2 and not second['changes'] and not writes
        assert json.loads((tmp_path / 'migration.json').read_text('utf8'))['facts_preserved']
        with engine.connect() as conn:
            conn.exec_driver_sql('ALTER TABLE holder_member DROP CHECK ck_holder_member_values, ADD CONSTRAINT ck_holder_member_values CHECK (ratio >= 0)')
            conn.commit()
        with pytest.raises(ValueError, match='未知持有人结构'):
            await migration.run(args)
    finally:
        engine.dispose()


async def test_pending_business_refuses_ddl(monkeypatch, tmp_path):
    cfg = load_config()
    monkeypatch.setattr(migration, 'load_config', lambda _: cfg)
    monkeypatch.setattr('empire.__main__.user_data_dir', lambda: tmp_path)
    client = create_client(cfg['redis'])
    key = cfg['redis']['namespace'] + ':ingest'
    try:
        ident = await client.xadd(key, {'envelope': 'retained'})
        with pytest.raises(ValueError, match='待归档非零'):
            await migration.run(SimpleNamespace(config=None, apply=True, report=str(tmp_path / 'report.json')))
        assert (await client.xrange(key))[0][0] == ident
    finally:
        await client.delete(key)
        await client.aclose()
