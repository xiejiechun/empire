"""Owned old-schema fixture upgrades source ranks without changing business facts."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.holders.contract import KINDS, report_key
from empire.features.holders.dataset import HolderDataset, read_reports
from empire.features.holders.source import parse
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from scripts import migrate_holder_source_rows as migration
from tests.test_ths_holders import STOCK, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Owned SQL integration')]


@pytest.fixture(autouse=True)
def owned_maintenance_lock(monkeypatch, tmp_path):
    # Use a real lock in this UUID-owned test's directory, not the desktop lock.
    monkeypatch.setattr('empire.__main__.user_data_dir', lambda: tmp_path)


async def test_old_rank_gaps_and_exit_order_preserved_on_upgrade_and_retry(monkeypatch, tmp_path):
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    client = create_client(cfg['redis'])
    mapping = HolderDataset()
    sections = {kind: parse(source(exit_order=True), kind, STOCK) for kind in KINDS}
    row = sections['bond_holders'][0]
    row['members'] = [m for m in row['members'] if m['member_group'] != 'current' or m['source_rank'] != 7]
    for i,m in enumerate([m for m in row['members'] if m['member_group']=='current'],1):
        m['seq'] = i
    row.update(total_quantity='900000', total_ratio='9')
    e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=mapping.JOB,
        business_key=STOCK['unified_code'], run_id='test', batch_id='test',
        payload=dict(page=1, unit=STOCK['unified_code'], reports=sections, manifest=None, gaps=[]))
    try:
        with engine.begin() as conn:
            data = mapping.normalize(e)
            mapping.write(conn, e, {**data, 'archive_state': {}})
        # Convert only this UUID-owned fixture to the previous official shape.
        with engine.connect() as conn:
            conn.exec_driver_sql('ALTER TABLE holder_report DROP CHECK ck_holder_totals, DROP COLUMN quality_flags, ADD CONSTRAINT ck_holder_totals CHECK (total_quantity>=0 AND total_ratio BETWEEN 0 AND 100.15)')
            conn.commit()
            conn.exec_driver_sql('ALTER TABLE holder_member DROP CHECK ck_holder_member_group')
            conn.commit()
            bonds = conn.execute(text("SELECT r.report_key,m.* FROM holder_report r JOIN holder_member m ON m.report_key=r.report_key WHERE r.kind='bond_holders' ORDER BY m.member_group,m.source_rank")).mappings().all()
            conn.commit()
            with conn.begin():
                key = report_key(row)
                conn.execute(text('DELETE FROM holder_member WHERE report_key=:key'), {'key': key})
                old_members = [{**m, 'seq': m['source_rank']} for m in bonds]
                names = tuple(old_members[0])
                conn.execute(text('INSERT INTO holder_member(' + ','.join(names) + ') VALUES(' + ','.join(':'+k for k in names) + ')'), old_members)
            conn.exec_driver_sql('ALTER TABLE holder_member DROP COLUMN source_rank, MODIFY ratio DECIMAL(9,4) NOT NULL, ADD CONSTRAINT ck_holder_member_group CHECK (member_group IN (\'current\',\'exited\') AND seq BETWEEN 1 AND 20)')
            conn.commit()
        monkeypatch.setattr(migration, 'load_config', lambda _: cfg)
        args = SimpleNamespace(config=None, apply=True, report=str(tmp_path/'migration.json'))
        await migration.run(args)
        first = json.loads(Path(args.report).read_text('utf8'))
        assert first['before'] == first['after'] and first['facts_preserved']
        with engine.connect() as conn:
            # Old exits were stored sorted by source rank, so normalize that order.
            for group in ('current','exited'):
                members = sorted([m for m in row['members'] if m['member_group']==group], key=lambda m:m['source_rank'])
                for i,m in enumerate(members,1):
                    m['seq'] = i
                row['members'] = [m for m in row['members'] if m['member_group']!=group] + members
            row['members'].sort(key=lambda m:(m['member_group'],m['seq']))
            assert read_reports(conn,[report_key(row)]) == [row]
        await migration.run(args)
        assert json.loads(Path(args.report).read_text('utf8'))['already_current']
    finally:
        engine.dispose()
        await client.aclose()


async def test_contract3_nullable_upgrade_partial_ddl_retry_preserves_facts(monkeypatch, tmp_path):
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    mapping = HolderDataset()
    sections = {kind: parse(source(), kind, STOCK) for kind in KINDS}
    e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=mapping.JOB,
        business_key=STOCK['unified_code'], run_id='test', batch_id='test',
        payload=dict(page=1, unit=STOCK['unified_code'], reports=sections, manifest=None, gaps=[]))
    try:
        with engine.begin() as conn:
            mapping.write(conn, e, {**mapping.normalize(e), 'archive_state': {}})
        with engine.connect() as conn:
            conn.exec_driver_sql('ALTER TABLE holder_report DROP CHECK ck_holder_totals, ADD CONSTRAINT ck_holder_totals CHECK (quality_flags BETWEEN 0 AND 31 AND (total_quantity IS NULL OR total_quantity>=0) AND (total_ratio IS NULL OR total_ratio BETWEEN 0 AND 100.15))')
            conn.commit()
            conn.exec_driver_sql('ALTER TABLE holder_member DROP CHECK ck_holder_member_precision, MODIFY quantity DECIMAL(24,4) NOT NULL, MODIFY quantity_scale BIGINT NOT NULL, MODIFY quantity_decimals SMALLINT NOT NULL, ADD CONSTRAINT ck_holder_member_precision CHECK (quantity_scale IN (1,10000,100000000) AND quantity_decimals BETWEEN 0 AND 4)')
            conn.commit()
            original = migration.inventory(conn, verify=True)
        monkeypatch.setattr(migration, 'load_config', lambda _: cfg)
        monkeypatch.setattr(migration, 'make_engine', lambda _: engine)
        def fail_member(conn, cursor, sql, params, context, many):
            if sql.startswith('ALTER TABLE holder_member DROP CHECK'):
                raise RuntimeError('owned interrupted DDL')
        event.listen(engine, 'before_cursor_execute', fail_member)
        args = SimpleNamespace(config=None, apply=True, report=str(tmp_path / 'nullable-migration.json'))
        with pytest.raises(RuntimeError, match='interrupted DDL'):
            await migration.run(args)
        event.remove(engine, 'before_cursor_execute', fail_member)
        await migration.run(args)
        result = json.loads(Path(args.report).read_text('utf8'))
        assert result['before'] == result['after'] == original
        await migration.run(args)
        assert json.loads(Path(args.report).read_text('utf8'))['already_current']
        with engine.connect() as conn:
            assert migration.inventory(conn, verify=True) == original
            with pytest.raises(Exception, match='ck_holder_member_precision'):
                conn.execute(text('UPDATE holder_member SET quantity=NULL WHERE seq=1'))
            conn.rollback()
    finally:
        engine.dispose()
