"""Real MySQL shadow switch, canonical inventories and interruption/rollback regression."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from scripts.business_migration_engine import migrate, rollback, verify
from scripts.business_migration_inventory import BACKUP, NEW, PREFIX, inventory

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit integration opt-in required')]


@pytest.fixture
def old_database():
    engine = make_engine(load_config()['mysql'])
    legacy = Path('sql/legacy/business-v1.sql').read_text(encoding='utf-8')
    with engine.begin() as conn:
        for table in NEW:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS `{table}`')
        legacy = '\n'.join(line for line in legacy.splitlines() if not line.lstrip().startswith('--'))
        for statement in legacy.split(';'):
            if statement.strip():
                conn.execute(text(statement))
        conn.exec_driver_sql("INSERT INTO stock VALUES('sina','hs_a','000001.SZ','000001','测试','SZ','sz000001')")
        conn.exec_driver_sql("INSERT INTO trade_calendar VALUES('cninfo','2026-09-30',1,'2026-09-30 12:00:00')")
        conn.exec_driver_sql("INSERT INTO income_statement VALUES('ths','SH','600001','2025-12-31',"
            "JSON_OBJECT('amount','1234567890.123456789','optional',NULL),'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','2026-01-01 10:00:00')")
        for note,dates in [('a',['2026-09-29','2026-09-30']),('b',None),('c',[])]:
            conn.execute(text('INSERT INTO suspension_event VALUES '
                "('tdx','SH','600001','历史证券','2026-09-01',NULL,'1000-01-01',:key,:dates,"
                "'full_day',:note,'原因','2026-09-30 12:00:00')"),
                dict(key=note*64, dates=json.dumps(dates) if dates is not None else None,note=note))
        conn.exec_driver_sql("INSERT INTO finance_news VALUES('a',1,'标题','内容','2026-01-01','2026-01-01',0,JSON_ARRAY(),'url','2026-01-01','2026-01-01')")
        conn.exec_driver_sql("INSERT INTO finance_news SELECT 'b',news_id,title,content,published_at,source_updated_at,is_important,tags,url,first_seen_at,version_observed_at FROM finance_news")
    yield engine
    engine.dispose()


def test_copy_resume_atomic_switch_and_rollback(old_database,tmp_path):
    engine = old_database
    path = tmp_path/'migration.json'
    before = inventory(engine,old=True)
    with pytest.raises(RuntimeError,match='injected'):
        migrate(engine,path,fail_after='stock')
    with engine.connect() as conn:
        assert 'source' in {c['name'] for c in inspect(conn).get_columns('stock')}
    result = migrate(engine,path)
    assert result['phase']=='verified'
    assert result['before']==result['after']==before
    assert migrate(engine,path)['phase']=='verified'
    assert verify(engine,path)['passed']
    with engine.connect() as conn:
        assert 'source' not in {c['name'] for c in inspect(conn).get_columns('stock')}
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM suspension_source_date').scalar_one()==2
        assert conn.exec_driver_sql('SELECT SUM(source_dates_known) FROM suspension_event').scalar_one()==1
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM finance_news').scalar_one()==2
    rollback(engine,path)
    assert inventory(engine,old=True)==before
    with engine.connect() as conn:
        assert all(PREFIX+t in inspect(conn).get_table_names() for t in NEW)
        assert BACKUP+'stock' not in inspect(conn).get_table_names()


def test_no_rollback_over_new_business_even_same_count(old_database,tmp_path):
    engine,path=old_database,tmp_path/'migration.json'
    migrate(engine,path)
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE stock SET name='新增版本'")
    with pytest.raises(ValueError,match='业务集合'):
        rollback(engine,path)


def test_reject_extra_source_before_copy(old_database,tmp_path):
    with old_database.begin() as conn:
        conn.exec_driver_sql("INSERT INTO industry VALUES('another','000001','保留来源')")
    with pytest.raises(ValueError,match='额外来源'):
        migrate(old_database,tmp_path/'migration.json')
    with old_database.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM industry').scalar_one()==1
        assert not any(t.startswith(PREFIX) for t in inspect(conn).get_table_names())


def test_actual_index_change_rejects_verification(old_database,tmp_path):
    path=tmp_path/'migration.json'
    migrate(old_database,path)
    with old_database.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE income_statement DROP INDEX ix_report_date')
    with pytest.raises(ValueError,match='实际结构'):
        verify(old_database,path)


def test_missing_stock_business_cannot_be_certified_by_publication(old_database,tmp_path):
    with old_database.begin() as conn:
        conn.exec_driver_sql("INSERT INTO collection_state(namespace,project_id,source,dataset,payload,updated_at) "
            "VALUES('test','sina-stocks','sina','stocks',JSON_OBJECT('publication',JSON_OBJECT('row_count',2)),NOW(6))")
    with pytest.raises(ValueError,match='股票业务数量'):
        migrate(old_database,tmp_path/'migration.json')
