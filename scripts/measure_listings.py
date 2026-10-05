"""UUID-owned schema capacity measurement on a separate MySQL instance."""
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

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.listings import COLUMNS, CONTRACT, DATASET, JOB, TABLE, digest, validate
from empire.core.config import load_config, project_root
from empire.core.time import mysql_time
from empire.plugins.datasets import listings
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    production = load_config()['mysql']
    if (settings.get('host'),settings.get('port')) == (production.get('host'),production.get('port')):
        raise ValueError('容量实验必须使用独立MySQL服务')
    admin, db, engine, created = make_engine(settings), 'empire_'+uuid4().hex+'_test', None, False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4')
            created = True
        settings = {**settings,'database':db}
        initialize_database(settings)
        engine, now = make_engine(settings), datetime.now(UTC)
        template = dict(listing_date='1991-04-03',establish_date='1987-12-22',issuance_num='350000',
            issuance_price='40',first_day_open_price='49',estimated_raised='27000000',actual_raised='14000000',
            issuance_pe=None,winning_rate=None,lead_underwriter='机构甲',sponsor='机构甲',history='文'*683)
        rows=[]
        for i in range(15000):
            row=validate(dict(unified_code=f'{i:06d}.SZ',**template), '2026-10-06')
            if i%20==0:
                row['history']='文'*9788  # Measured sample high end, 29364 bytes.
            rows.append(row)
        columns=(*COLUMNS,'content_hash','contract_version','version_observed_at')
        sql=text(f'INSERT INTO {TABLE} ({",".join(columns)}) VALUES ({",".join(":"+k for k in columns)})')
        tracemalloc.start()
        started=time.perf_counter()
        with engine.begin() as conn:
            for offset in range(0,len(rows),200):
                conn.execute(sql,[{**r,'content_hash':digest(r),'contract_version':CONTRACT,'version_observed_at':mysql_time(now)} for r in rows[offset:offset+200]])
        import_seconds=time.perf_counter()-started
        peak=tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        e=make_envelope(source='ths',dataset=DATASET,business_key='SZ:000001',job_key=JOB,
            batch_id='measure',run_id='measure',payload=dict(page=1,unit='SZ:000001',row=rows[1],manifest=None))
        e=e.model_copy(update={'observed_at':now})
        data={**listings.normalize(e),'archive_state':{}}
        with engine.begin() as conn:
            repeat=listings.write(conn,e,data)
            revision=listings.write(conn,e,{**data,'row':{**rows[1],'issuance_price':'41'}})
        assert repeat['written_count']==0 and revision['written_count']==1
        sqls={
            'page': 'SELECT unified_code,listing_date,issuance_num,issuance_price FROM stock_listing ORDER BY listing_date,unified_code LIMIT 200',
            'detail': "SELECT * FROM stock_listing WHERE unified_code='000020.SZ'",
            'range': "SELECT unified_code,listing_date FROM stock_listing WHERE listing_date BETWEEN '1990-01-01' AND '2000-01-01' ORDER BY listing_date,unified_code LIMIT 200",
            'coverage': 'SELECT unified_code,listing_date,content_hash,contract_version FROM stock_listing ORDER BY unified_code LIMIT 15001',
        }
        timings,explains,actual={}, {}, {}
        with engine.connect() as conn:
            version=conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            conn.exec_driver_sql('ANALYZE TABLE stock_listing')
            for name,query in sqls.items():
                samples=[]
                for _ in range(20):
                    started=time.perf_counter()
                    result=conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter()-started)*1000)
                timings[name]=sorted(samples)[18]
                actual[name]=dict(returned=len(result),read_bytes=len(json.dumps([list(r) for r in result],ensure_ascii=False,default=str).encode()))
                explains[name]=[dict(r) for r in conn.exec_driver_sql('EXPLAIN '+query).mappings()]
            allocation=conn.execute(text("SELECT data_length+index_length FROM information_schema.tables WHERE table_schema=:db AND table_name='stock_listing'"),{'db':db}).scalar_one()
            started=time.perf_counter()
            after,audited='',0
            while True:
                records=conn.execute(text('SELECT * FROM stock_listing WHERE unified_code>:after ORDER BY unified_code LIMIT 200'),{'after':after}).mappings().all()
                for record in records:
                    row=listings.decode(record)
                    assert digest(validate(row,'2026-10-06'))==record['content_hash']
                    audited+=1
                if len(records)<200:
                    break
                after=records[-1]['unified_code']
            audit_seconds=time.perf_counter()-started
        bindings=['src/empire/contracts/listings.py','src/empire/plugins/datasets/listings.py',
                  'src/empire/plugins/data/listings.py','scripts/measure_listings.py']
        ddl=re.search(r'CREATE TABLE IF NOT EXISTS stock_listing\s*\([\s\S]*?;', (root/'sql/schema.sql').read_text()).group()
        report=dict(bindings={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings},
            ddl_scopes={TABLE:hashlib.sha256(ddl.encode()).hexdigest()},
            measurements=dict(page_p95_ms=timings['page'],detail_p95_ms=timings['detail'],range_p95_ms=timings['range'],
                coverage_p95_ms=timings['coverage'],import_seconds=import_seconds,audit_seconds=audit_seconds,allocated_bytes=int(allocation)),
            limits=dict(page_p95_ms=50,detail_p95_ms=50,range_p95_ms=50,coverage_p95_ms=500,import_seconds=60,audit_seconds=5,allocated_bytes=1536*1024**2),
            conditions=dict(platform=platform.platform(),mysql=version,rows=15000,audited=audited,cache='unforced first; subsequent hot repetitions',
                synthetic=True,history_sizes_bytes=[2049,29364],maximum_history_bytes=65536),
            reviewed_tradeoffs='一证券一行；列表/补缺不读历史沿革；详细审计有界200行页读正文，来源范围只限当前池和已存记录。容量按真实正文尺寸放大，不代表全市场实采。',
            explain=explains,queries=actual,python_peak_bytes=peak,repeat=repeat,revision=revision,
            cleanup='UUID-owned database dropped in finally')
        report['passed']=all(report['measurements'][k]<=v for k,v in report['limits'].items())
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(passed=report['passed'],measurements=report['measurements'])))
        if not report['passed']:
            raise RuntimeError('容量预算未通过')
    finally:
        if engine:
            engine.dispose()
        if created:
            assert db.endswith('_test')
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{db}`')
        admin.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings',required=True)
    parser.add_argument('--output',default='docs/evidence/listings-capacity-2026-10-06.json')
    run(parser.parse_args())
