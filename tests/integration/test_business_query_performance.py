"""Reproducible before/after query plans on an isolated representative data set."""
import json
import os
import statistics
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from test_business_schema_migration import old_database as old_database

from scripts.business_migration_engine import migrate

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit integration opt-in required')]


def measure(engine, query):
    with engine.connect() as conn:
        plan=[dict(r) for r in conn.execute(text('EXPLAIN '+query)).mappings()]
        times=[]
        for _ in range(5):
            start=time.perf_counter()
            rows=conn.execute(text(query)).all()
            times.append(time.perf_counter()-start)
    return dict(plan=plan, seconds=times, median_seconds=statistics.median(times)),rows


def test_formal_date_queries_preserve_results_and_use_new_indexes(old_database,tmp_path):
    engine=old_database
    with engine.begin() as conn:
        for offset in range(0,12000,500):
            rows=[dict(code=f'{i//12:06d}', day=date(2023,1,1)+timedelta(days=i%12),
                       payload=json.dumps({'i':i,'body':'x'*2048})) for i in range(offset,offset+500)]
            conn.execute(text("INSERT INTO income_statement VALUES('ths','SZ',:code,:day,:payload,REPEAT('a',64),'2026-01-01')"),rows)
            for i,row in enumerate(rows,offset):
                row['record_key']=f'{i:064x}'
            conn.execute(text("INSERT INTO dividend_plan VALUES('tdx',:record_key,'SZ',:code,'测试',"
                ":day,:payload,REPEAT('a',64),'2026-01-01')"),rows)
        conn.exec_driver_sql("INSERT INTO suspension_event SELECT 'tdx','SZ',code,'历史证券',"
            "'2023-01-01',NULL,'1000-01-01',record_key,JSON_ARRAY(CAST(event_date AS CHAR)),"
            "'full_day','说明','原因','2026-01-01' FROM dividend_plan")
    old="""SELECT s.payload FROM income_statement s JOIN (
        SELECT source,market,code,report_date FROM income_statement
        WHERE source='ths' AND market IN ('BJ','SH','SZ') AND code LIKE '%'
        ORDER BY report_date DESC,market,code LIMIT 51 OFFSET 0) chosen
        USING(source,market,code,report_date) ORDER BY s.report_date DESC,s.market,s.code"""
    new="""SELECT s.payload FROM income_statement s JOIN (
        SELECT unified_code,report_date FROM income_statement
        ORDER BY report_date DESC,RIGHT(unified_code,2),unified_code LIMIT 51 OFFSET 0) chosen
        USING(unified_code,report_date) ORDER BY s.report_date DESC,RIGHT(s.unified_code,2),s.unified_code"""
    old_capital="""SELECT record_key FROM dividend_plan WHERE source='tdx'
        ORDER BY event_date DESC,market,code,record_key LIMIT 51"""
    new_capital="""SELECT record_key FROM dividend_plan
        ORDER BY event_date DESC,RIGHT(unified_code,2),unified_code,record_key LIMIT 51"""
    old_dates="""SELECT record_key FROM suspension_event WHERE source='tdx'
        AND JSON_CONTAINS(source_dates,JSON_QUOTE('2023-01-12'))
        ORDER BY suspended_at DESC,market,code,resume_key,record_key LIMIT 51"""
    new_dates="""SELECT s.record_key FROM suspension_event s JOIN
        (SELECT DISTINCT unified_code,suspended_at,resume_key,record_key FROM suspension_source_date FORCE INDEX(PRIMARY)
        WHERE source_date>='2023-01-12' AND source_date<'2023-01-13') d
        USING(unified_code,suspended_at,resume_key,record_key)
        ORDER BY s.suspended_at DESC,RIGHT(s.unified_code,2),s.unified_code,s.resume_key,s.record_key LIMIT 51"""
    before,old_rows=measure(engine,old)
    before_capital,old_capital_rows=measure(engine,old_capital)
    before_dates,old_date_rows=measure(engine,old_dates)
    started=time.perf_counter()
    migrate(engine,tmp_path/'migration.json')
    copy_seconds=time.perf_counter()-started
    after,new_rows=measure(engine,new)
    after_capital,new_capital_rows=measure(engine,new_capital)
    after_dates,new_date_rows=measure(engine,new_dates)
    assert old_rows==new_rows
    assert old_capital_rows==new_capital_rows and old_date_rows==new_date_rows
    assert any(r['key']=='ix_report_date' for r in after['plan'])
    assert any(r['key']=='ix_event_date' for r in after_capital['plan'])
    assert any(r['table']=='suspension_source_date' and r['key']=='PRIMARY' for r in after_dates['plan']), after_dates
    report=dict(before=before,after=after,migration_seconds=copy_seconds,rows=12001,
                capital=dict(before=before_capital,after=after_capital),
                suspension_dates=dict(before=before_dates,after=after_dates),
                scope='isolated synthetic reports; five sequential warm runs; no physical disk/cold-cache claim')
    with engine.connect() as conn:
        report['index_bytes']=int(conn.execute(text('SELECT INDEX_LENGTH FROM information_schema.TABLES '
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='income_statement'")).scalar_one())
    path=Path('build/mysql-upgrade-final/query-performance.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
