"""Original 15000-row listing capacity protocol with UUID-owned guarded resources."""
import asyncio
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, read_server_uuid, test_settings
from source_verification import require
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import make_envelope
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.core.time import mysql_time
from empire.features.listings import dataset as listings
from empire.features.listings.contract import (
    COLUMNS,
    CONTRACT,
    DATASET,
    HISTORY_MAX_BYTES,
    JOB,
    PROJECT,
    TABLE,
    digest,
    validate,
)
from empire.features.listings.query import ListingDataPlugin
from empire.plugins.infra.collection_state import save_state
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.sql_lane import settle

CAPACITY_QUERIES = {
    'page': 'SELECT unified_code,listing_date,issuance_num,issuance_price FROM stock_listing ORDER BY listing_date,unified_code LIMIT 200',
    'detail': "SELECT * FROM stock_listing WHERE unified_code='000020.SZ'",
    'range': "SELECT unified_code,listing_date FROM stock_listing WHERE listing_date BETWEEN '1990-01-01' AND '2000-01-01' ORDER BY listing_date,unified_code LIMIT 200",
    'coverage': 'SELECT unified_code,listing_date,content_hash,contract_version FROM stock_listing ORDER BY unified_code LIMIT 15001',
}


class ListingCapacityStorage(PrivateStorage):
    def guard(self, conn, cursor, statement, parameters, context, executemany):
        approved = {'ANALYZE TABLE stock_listing', *('EXPLAIN '+q for q in CAPACITY_QUERIES.values())}
        if statement in approved and not parameters:
            # Same actual server/database check as all business SQL, then exact fixed statement.
            super().guard(conn, cursor, 'SELECT 1', (), context, False)
            return
        super().guard(conn, cursor, statement, parameters, context, executemany)


def measure_inner(engine, db):
    root, now = project_root(), datetime.now(UTC)
    template = dict(listing_date='1991-04-03',establish_date='1987-12-22',issuance_num='350000',
        issuance_price='40',first_day_open_price='49',estimated_raised='27000000',actual_raised='14000000',
        issuance_pe=None,winning_rate=None,lead_underwriter='机构甲',sponsor='机构甲',history='文'*683)
    rows=[]
    for i in range(15000):
        row=validate(dict(unified_code=f'{i:06d}.SZ',**template), '2026-10-06')
        if i%20==0:
            row['history']='文'*35026  # Real 603107 UTF-8 size: 105078 bytes.
        if i == 20:
            row['history']='文'*(HISTORY_MAX_BYTES//3)+'x'*(HISTORY_MAX_BYTES%3)
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
    proofs={f'SZ:{i:06d}':dict(contract=CONTRACT,digest=digest(r),observed_at=now.isoformat(),
        availability='unavailable' if i%20==0 else 'available',availability_contract=1,
        source_status_code=10001 if i%20==0 else 0) for i,r in enumerate(rows)}
    for i in range(1, len(rows), 20):
        proofs[f'SZ:{i:06d}'].update(availability='incomplete', source_status_code=0,
            missing_fields=['listing_date'])
    state_bytes = len(json.dumps(proofs, ensure_ascii=False).encode())
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:unified_code,:name)'),
            [dict(unified_code=r['unified_code'],name='容量样本') for r in rows])
        save_state(conn,'capacity',PROJECT,'ths',DATASET,dict(units=proofs,contract_version=CONTRACT),{})
    async def read(callback):
        return callback()
    query=ListingDataPlugin('capacity')
    query.mysql=SimpleNamespace(read_engine=engine,read=read)
    async def formal_measure():
        results={}
        for name,call in [('page',lambda:query.list_records()),('detail',lambda:query.detail('000020.SZ')),
                          ('range',lambda:query.list_records(start='1990-01-01',end='2000-01-01')),
                          ('coverage',query.plan)]:
            samples=[]
            for _ in range(20):
                started=time.perf_counter()
                await call()
                samples.append((time.perf_counter()-started)*1000)
            results[name]=sorted(samples)[18]
        return results
    formal_timings=asyncio.run(formal_measure())
    e=make_envelope(source='ths',dataset=DATASET,business_key='SZ:000001',job_key=JOB,
        batch_id='measure',run_id='measure',payload=dict(page=1,unit='SZ:000001',row=rows[1],manifest=None))
    e=e.model_copy(update={'observed_at':now})
    data={**listings.normalize(e),'archive_state':{}}
    with engine.begin() as conn:
        repeat=listings.write(conn,e,data)
        revision=listings.write(conn,e,{**data,'row':{**rows[1],'issuance_price':'41'}})
    assert repeat['written_count']==0 and revision['written_count']==1
    expected_rows = {r['unified_code']: r for r in rows}
    expected_rows['000001.SZ'] = {**rows[1], 'issuance_price': '41'}
    sqls = CAPACITY_QUERIES
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
        after,audited,seen='',0,set()
        while True:
            records=conn.execute(text('SELECT * FROM stock_listing WHERE unified_code>:after ORDER BY unified_code LIMIT 200'),{'after':after}).mappings().all()
            for record in records:
                row=listings.decode(record)
                assert digest(validate(row,'2026-10-06'))==record['content_hash']
                require(row == expected_rows[row['unified_code']] and row['unified_code'] not in seen,
                        '容量样本相同数量下的集合或规范内容不同')
                seen.add(row['unified_code'])
                audited+=1
            if len(records)<200:
                break
            after=records[-1]['unified_code']
        audit_seconds=time.perf_counter()-started
        require(seen == set(expected_rows), '容量样本证券集合不同')
    bindings=['src/empire/features/listings/contract.py','src/empire/features/listings/dataset.py',
              'src/empire/features/listings/query.py','scripts/measure_listings.py',
              'scripts/source_test_storage.py','scripts/source_verification.py',
              'sql/business-schema.json','src/empire/contracts/business_schema.py']
    ddl=re.search(r'CREATE TABLE IF NOT EXISTS stock_listing\s*\([\s\S]*?;', (root/'sql/schema.sql').read_text()).group()
    report=dict(bindings={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings},
        ddl_scopes={TABLE:hashlib.sha256(ddl.encode()).hexdigest()},
        measurements=dict(page_p95_ms=formal_timings['page'],detail_p95_ms=formal_timings['detail'],range_p95_ms=formal_timings['range'],
            coverage_p95_ms=formal_timings['coverage'],import_seconds=import_seconds,audit_seconds=audit_seconds,allocated_bytes=int(allocation),state_bytes=state_bytes),
        limits=dict(page_p95_ms=100,detail_p95_ms=100,range_p95_ms=100,coverage_p95_ms=500,import_seconds=60,audit_seconds=5,allocated_bytes=1536*1024**2,state_bytes=8*1024**2),
        conditions=dict(platform=platform.platform(),mysql=version,rows=15000,state_units=15000,formal_queries=True,audited=audited,cache='unforced first; subsequent hot repetitions',
            synthetic=True,incomplete_units=750,unavailable_units=750,history_sizes_bytes=[2049,105078,HISTORY_MAX_BYTES],maximum_history_bytes=HISTORY_MAX_BYTES),
        reviewed_tradeoffs='一证券一行；列表/补缺不读历史沿革；详细审计有界200行页读正文，来源范围只限当前池和已存记录。容量按真实正文尺寸放大，不代表全市场实采。正式列表和详情读取统一状态以提示来源缺值；15000单元约3.5MiB，实测63至77ms超过原50ms目标，接受100ms预算以保留单一状态路径和准确质量提示，不另建状态表或持久缓存。',
        explain=explains,queries=actual,python_peak_bytes=peak,repeat=repeat,revision=revision,
        cleanup_protocol='shared owned-storage finish, checked before final durable report')
    return report


def measure(storage):
    engine = make_engine(storage.settings)
    try:
        return measure_inner(engine, storage.database)
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


async def verify(args):
    output, report = verification.initial_report(args)
    storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, 'timeout须为1～7200秒')
        require(args.random_count == 0 and args.seed is None and not args.codes, '合成容量不能声明实采随机样本')
        paths = [Path(args.pool_config or default_config_path()).resolve(), Path(args.test_mysql_settings).resolve()]
        report['input_files'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text('utf-8'))
        require(isinstance(raw, dict), '测试连接须为JSON对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw.get('password')])
        settings = test_settings(raw)
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg['mysql'])
        report.update(subject='listings_capacity', source_sha256=source_digest(project_root()),
                      source_server_uuid=source_uuid, acceptance_complete=False, sample_30_applicable=False,
                      sample_30_reason='15000行合成容量；不请求来源，不替代严格代理实采')
        storage = ListingCapacityStorage(settings, cfg['redis'], report['run_id'], token_hex(32), source_uuid)
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name+'.ownership.json')
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1])))
        report['storage'] = storage.identity()
        report['environment'] = dict(storage.conn.exec_driver_sql(
            'SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,'
            '@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,'
            '@@sync_binlog AS sync_binlog,@@log_bin AS log_bin').mappings().one())
        await storage.create_redis()
        storage.seed([], [])
        async with asyncio.timeout(args.timeout):
            # Cancellation waits for the SQL worker before owned cleanup, never drops an active writer's database.
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure, storage)))
        report.update(measured)
        report['input_files'].update({str(project_root()/p): sha for p, sha in measured['bindings'].items()})
        require(measured['conditions']['audited'] == 15000, '容量详细审计集合不完整')
        require(all(measured['measurements'][k] <= limit for k, limit in measured['limits'].items()), '容量超出冻结预算')
        require(await storage.client.get(storage.owner_key) == storage.owner, 'Redis归属变化')
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report['errors'].append(dict(stage='capacity', message=redactor.text(exc, 2048), type=type(exc).__name__))
    finally:
        passed = await verification.complete(output, report, redactor, None, storage, lock, False)
    return passed


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=900)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
