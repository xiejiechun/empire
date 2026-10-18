"""Private independent MySQL measurement of typed events and full monthly writes."""
import argparse
import hashlib
import json
import platform
import re
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, text

from empire.contracts.tdx_performance import columns, digest, identity
from empire.core.config import load_config, project_root
from empire.core.time import mysql_time
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from empire.plugins.datasets.tdx_performance import PerformanceDataset
from empire.plugins.infra.mysql_store import make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    production = load_config()['mysql']
    if (settings['host'], settings['port']) == (production['host'], production['port']):
        raise ValueError('容量放大必须独立测试服务')
    proof = json.loads((root/'docs/evidence/shareholder-changes-live-2026-10-13.json').read_text('utf8'))
    seed = proof['representative_row']
    admin, engine = make_engine(settings), None
    database, created = 'empire_change_' + uuid4().hex + '_test', False
    kind, table = 'shareholder_changes', 'shareholder_change'
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            created = True
        engine = make_engine({**settings, 'database': database})
        ddl = re.search(r'CREATE TABLE IF NOT EXISTS shareholder_change\s*\([\s\S]*?;',
            (root/'sql/schema.sql').read_text('utf8'))[0]
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl)
        stamp = datetime.now(UTC)
        names = ('record_key', *columns(kind), 'content_hash', 'version_observed_at')
        insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES('+','.join(':'+k for k in names)+')')
        started, unit = time.perf_counter(), []
        for month in range(20):
            period = f'{2020+month//12}-{month%12+1:02d}-01'
            values = []
            for security in range(5000):
                row = {**seed, 'unified_code': f'{security:06d}.SH', 'data_month': period, 'change_end': period[:8]+'15',
                       'change_start': None, 'announcement_date': period[:8]+'16', 'occurrence': 1}
                values.append({**row, 'record_key': identity(kind, row), 'content_hash': digest(row), 'version_observed_at': mysql_time(stamp)})
                if month == 0:
                    unit.append(row)
            with engine.begin() as conn:
                for offset in range(0,len(values),300):
                    conn.execute(insert, values[offset:offset+300])
        imported = time.perf_counter()-started
        unit.sort(key=lambda r: identity(kind,r))
        mapping = PerformanceDataset(kind)
        envelope = PerformanceCollector(kind).envelope('2020-01-01|SH', unit, 1, 'capacity', stamp)
        packed_bytes = len(envelope.model_dump_json().encode())
        decoded_bytes = len(json.dumps([[r[k] for k in columns(kind)] for r in unit],ensure_ascii=False,separators=(',',':')).encode())
        dml = []
        def capture(conn,cursor,statement,parameters,context,executemany):
            if table in statement and statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')):
                dml.append(statement)
        event.listen(engine,'before_cursor_execute',capture)
        data = dict(unit='2020-01-01|SH', rows=unit, row_count=len(unit), archive_state={})
        started = time.perf_counter()
        with engine.begin() as conn:
            repeat = mapping.write(conn,envelope,data)
        repeated = time.perf_counter()-started
        assert not dml and repeat['written_count']==0
        changed = [{**row,'name':'容量修订'} if i==0 else row for i,row in enumerate(unit)]
        started = time.perf_counter()
        with engine.begin() as conn:
            revision = mapping.write(conn,envelope,{**data,'rows':changed})
        revision_seconds = time.perf_counter()-started
        assert revision['written_count']==1
        event.remove(engine,'before_cursor_execute',capture)
        queries = dict(page='SELECT * FROM shareholder_change FORCE INDEX (ix_date) ORDER BY change_end DESC,unified_code DESC,record_key DESC LIMIT 200',
            security="SELECT * FROM shareholder_change FORCE INDEX (ix_security_date) WHERE unified_code='000000.SH' ORDER BY change_end DESC,record_key DESC LIMIT 200",
            detail="SELECT * FROM shareholder_change WHERE record_key='"+identity(kind,unit[0])+"'",
            month="SELECT * FROM shareholder_change WHERE data_month='2020-01-01' ORDER BY unified_code,record_key LIMIT 10000",
            range="SELECT unified_code,change_end,shares_changed FROM shareholder_change FORCE INDEX (ix_date) WHERE change_end BETWEEN '2020-01-01' AND '2020-12-31' ORDER BY change_end DESC,unified_code DESC,record_key DESC LIMIT 200")
        timings, returned, plans, peaks = {}, {}, {}, {}
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            for label,query in queries.items():
                samples=[]
                for _ in range(5):
                    started=time.perf_counter()
                    rows=conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter()-started)*1000)
                timings[label],returned[label]=max(samples),len(rows)
                tracemalloc.start()
                rows=conn.exec_driver_sql(query).all()
                peaks[label]=tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                plans[label]=[dict(r) for r in conn.exec_driver_sql('EXPLAIN '+query).mappings()]
            conn.exec_driver_sql('ANALYZE TABLE shareholder_change')
            allocated=int(conn.execute(text('SELECT data_length+index_length FROM information_schema.tables WHERE table_schema=:db AND table_name=:t'),dict(db=database,t=table)).scalar_one())
        measurements={**{key+'_ms':v for key,v in timings.items()},'allocated_bytes':allocated,
            'projected_million_bytes':allocated*10,'import_seconds':imported,'repeat_seconds':repeated,
            'revision_seconds':revision_seconds,'message_bytes':packed_bytes,'matrix_bytes':decoded_bytes,'query_peak_bytes':max(peaks.values())}
        limits={**{key+'_ms':5000 if key=='month' else 100 for key in timings},'allocated_bytes':256*1024**2,
            'projected_million_bytes':2*1024**3,'import_seconds':120,'repeat_seconds':5,'revision_seconds':5,
            'message_bytes':524288,'matrix_bytes':8*1024**2,'query_peak_bytes':32*1024**2}
        paths=['src/empire/contracts/tdx_performance.py','src/empire/plugins/datasets/tdx_performance.py',
               'src/empire/plugins/data/tdx_performance.py','scripts/measure_shareholder_changes.py']
        report=dict(checked_at=datetime.now(UTC).isoformat(),bindings={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={table:hashlib.sha256(ddl.encode()).hexdigest()},measurements=measurements,limits=limits,
            conditions=dict(platform=platform.platform(),mysql=version,independent_service=True,rows=100000,
                cache='first unforced plus four warm; maximum conservatively bounds P95',source='real normalized early event expanded across 5000 securities and 20 months'),
            reviewed_tradeoffs='事实列与三个业务查询索引；开始日期严格保留月/日精度的VARCHAR(10)，不伪造日。测完整5000行市场重复零DML及单行修订；估计百万行是线性投影而非生产实采或冷盘承诺。',
            details=dict(query_ms=timings,returned=returned,explain=plans,repeated_business_dml=0,revised_rows=revision['written_count']),
            passed=all(measurements[k]<=v for k,v in limits.items()))
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf8')
        print(json.dumps(dict(passed=report['passed'],measurements=measurements)))
        if not report['passed']:
            raise ValueError('容量预算未通过')
    finally:
        if engine:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings',required=True)
    parser.add_argument('--output',default='docs/evidence/shareholder-changes-capacity-2026-10-13.json')
    run(parser.parse_args())
