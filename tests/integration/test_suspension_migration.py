import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from empire.core.config import load_config, project_root
from empire.features.suspensions.contract import record_key
from empire.plugins.infra.mysql_store import make_engine
from scripts.migrate_suspension_identity import migrate_schema

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


def test_identity_migration_preserves_rows_and_allows_distinct_source_records():
    engine = make_engine(load_config()['mysql'])
    table = 'test_suspension_'+uuid4().hex
    schema = (project_root()/'sql/legacy/business-v1.sql').read_text(encoding='utf-8')
    ddl = 'CREATE TABLE '+table+schema.split('CREATE TABLE IF NOT EXISTS suspension_event', 1)[1].split(';', 1)[0]
    ddl = ddl.replace('    resume_key DATETIME(6) NOT NULL,\n', '')
    ddl = ddl.replace('    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n', '')
    ddl = ddl.replace('    source_dates JSON NULL,\n', '')
    ddl = ddl.replace('suspended_at, resume_key, record_key)', 'suspended_at)')
    ddl = '\n'.join(line for line in ddl.splitlines() if 'CONSTRAINT ck_suspension_resume_key' not in line)
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
            conn.execute(text(f"INSERT INTO {table} VALUES ('test','SH','600002','测试',"
                              "'2006-02-08 09:30','2006-02-09 09:30','full_day','停牌1天','公告',NOW())"))
        report = migrate_schema(engine, table)
        assert report['before'] == report['after'] and report['before']['rows'] == 1
        assert migrate_schema(engine, table)['before'] == report['before']
        with engine.begin() as conn:
            assert conn.execute(text(f'SELECT source_dates FROM {table}')).scalar_one() is None
            common = {'source': 'test', 'market': 'SH', 'code': '600002', 'name': '测试',
                      'suspended_at': '2006-02-08 09:30', 'suspension_type': 'full_day',
                      'version_observed_at': '2006-02-28 12:00'}
            rows = [
                {**common, 'resumed_at': '2006-02-17 09:30', 'resume_key': '2006-02-17 09:30',
                 'source_note': '今起复牌', 'reason': '公告'},
                {**common, 'resumed_at': '2006-02-09 09:30', 'resume_key': '2006-02-09 09:30',
                 'source_note': '另一说明', 'reason': '另一原因'},
            ]
            for row in rows:
                row['record_key'] = record_key(row)
                conn.execute(text(f"""INSERT INTO {table}
                    (source,market,code,name,suspended_at,resumed_at,suspension_type,source_note,
                     reason,version_observed_at,resume_key,record_key)
                    VALUES (:source,:market,:code,:name,:suspended_at,:resumed_at,:suspension_type,
                     :source_note,:reason,:version_observed_at,:resume_key,:record_key)"""), row)
            assert conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one() == 3
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
        engine.dispose()
