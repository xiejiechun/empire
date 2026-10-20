"""Original five-entity and shareholder-change capacity protocols on owned storage."""
import asyncio
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from secrets import token_hex

import source_verification as verification
from performance_storage import PerformanceStorage
from PySide6.QtCore import QCoreApplication
from source_test_storage import read_server_uuid, test_settings
from source_verification import require
from sqlalchemy import event, text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import make_envelope
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.core.time import mysql_time
from empire.features.performance.collector import PerformanceCollector
from empire.features.performance.contract import KINDS, columns, digest, identity, source_row
from empire.features.performance.dataset import PerformanceDataset, decode
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.sql_lane import settle


def bindings(family):
    paths=['src/empire/features/performance/'+name+'.py' for name in ('contract','source','collector','dataset','query')]
    paths += ['scripts/performance_capacity.py','scripts/measure_'+('tdx_performance' if family=='performance' else 'shareholder_changes')+'.py',
        'scripts/performance_storage.py','scripts/source_test_storage.py','scripts/source_verification.py','src/empire/contracts/business_schema.py','sql/business-schema.json',
        'docs/evidence/tdx-performance-probe-2026-10-12.json' if family=='performance' else 'docs/evidence/shareholder-changes-live-2026-10-13.json']
    return {p:hashlib.sha256((project_root()/p).read_bytes()).hexdigest() for p in paths}


class PerformanceCapacityStorage(PerformanceStorage):
    def __init__(self,*args,**kwargs):
        self.explain_sql=set()
        super().__init__(*args,**kwargs)

    def guard(self,conn,cursor,statement,parameters,context,executemany):
        tables={item[1] for item in KINDS.values()}|{'shareholder_change'}
        if statement in {'ANALYZE TABLE '+table for table in tables} and not parameters and not executemany:
            return super().guard(conn,cursor,'SELECT 1',(),context,False)
        if statement in self.explain_sql and not parameters and not executemany:
            return super().guard(conn,cursor,statement[8:],(),context,False)
        return super().guard(conn,cursor,statement,parameters,context,executemany)


def verify_table(conn,kind,expected):
    table=PerformanceDataset(kind).table
    actual=conn.exec_driver_sql('SELECT * FROM '+table+' ORDER BY record_key').mappings()
    rows=[]
    for raw in actual:
        row=decode(kind,raw)
        require(raw['record_key']==identity(kind,row) and raw['content_hash']==digest(row),'容量业务键或内容摘要不同')
        rows.append([raw['record_key'],digest(row)])
    require(rows==sorted(expected),'容量全表集合或内容不符')

def measure_performance(storage):
    root = project_root()
    engine = make_engine(storage.settings)
    database = storage.database
    proof = json.loads((root/'docs/evidence/tdx-performance-probe-2026-10-12.json').read_text('utf8'))
    sql = (root/'sql/schema.sql').read_text('utf8')
    measured, ddl_scopes, seeds = {}, {}, {}
    try:
        for kind, (_, table, suffix, _) in KINDS.items():
            source = next(v for v in proof['results'] if v['label'] == suffix + '_10000')
            raw = dict(zip(source['sets'][0]['columns'], source['sets'][0]['samples'][0], strict=True))
            seed = source_row(kind, raw)
            seeds[kind] = seed
            statement = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)[0]
            ddl_scopes[table] = hashlib.sha256(statement.encode()).hexdigest()
            names = ('record_key', *columns(kind), 'content_hash', 'version_observed_at')
            insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
            stamp = datetime.now(UTC)
            sample_unit = []
            expected = []
            started = time.perf_counter()
            for block in range(20):
                period = f'{2020 + block // 4}-{("03-31", "06-30", "09-30", "12-31")[block % 4]}'
                values = []
                for security in range(5000):
                    row = {**seed, 'unified_code': f'{security:06d}.SH'}
                    field = 'statistics_date' if kind == 'holder_count' else 'report_date'
                    row[field] = period
                    if kind != 'holder_count' and 'announcement_date' in row:
                        row['announcement_date'] = (date.fromisoformat(period) + timedelta(days=60)).isoformat()
                    if kind == 'holder_count' and security == 0 or kind != 'holder_count' and block == 0:
                        sample_unit.append(row)
                    values.append({**row, 'record_key': identity(kind, row), 'content_hash': digest(row),
                                   'version_observed_at': mysql_time(stamp)})
                expected.extend([v['record_key'],v['content_hash']] for v in values)
                with engine.begin() as conn:
                    for offset in range(0, len(values), 500):
                        conn.execute(insert, values[offset:offset + 500])
            import_seconds = time.perf_counter() - started
            with engine.connect() as conn:
                verify_table(conn,kind,expected)
            del values
            mapping = PerformanceDataset(kind)
            sample_unit.sort(key=lambda r: identity(kind, r))
            unit = '000000.SH' if kind == 'holder_count' else '2020-03-31|SH'
            envelope = make_envelope(source='tdx', dataset=kind + '.tdx_unit', job_key=mapping.JOB,
                business_key=unit, batch_id='capacity', run_id='capacity', payload={}).model_copy(update={'observed_at': stamp})
            data = dict(unit=unit, rows=sample_unit, row_count=len(sample_unit), archive_state={})
            dml = []
            def capture(conn, cursor, statement, parameters, context, executemany):
                if table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                    dml.append(statement)
            event.listen(engine, 'before_cursor_execute', capture)
            with engine.begin() as conn:
                repeat = mapping.write(conn, envelope, data)
            assert not dml and repeat['written_count'] == 0
            repeat_dml = len(dml)
            changed = [{**r, 'name': '容量修订'} if index == 0 else r for index, r in enumerate(sample_unit)]
            with engine.begin() as conn:
                revision = mapping.write(conn, envelope, {**data, 'rows': changed})
            assert revision['written_count'] == 1
            event.remove(engine, 'before_cursor_execute', capture)
            field = 'statistics_date' if kind == 'holder_count' else 'report_date'
            queries = {
                'page': f'SELECT * FROM {table} ORDER BY {field} DESC,unified_code DESC,record_key DESC LIMIT 200',
                'security': f"SELECT * FROM {table} WHERE unified_code='000000.SH' ORDER BY {field} DESC,record_key DESC LIMIT 200",
                'detail': f"SELECT * FROM {table} WHERE record_key='{identity(kind, sample_unit[0])}'",
                'range': f"SELECT unified_code,{field} FROM {table} WHERE {field}>='2021-01-01' AND {field}<='2024-12-31' ORDER BY {field} DESC,unified_code DESC,record_key DESC LIMIT 200",
                'coverage': f'SELECT record_key,content_hash FROM {table} ORDER BY record_key LIMIT 100001',
            }
            unit_filter = "unified_code='000000.SH'" if kind == 'holder_count' else "report_date='2020-03-31' AND unified_code LIKE '%%.SH'"
            queries['unit'] = f'SELECT /*+ MAX_EXECUTION_TIME(15000) */ * FROM {table} WHERE {unit_filter} ORDER BY record_key LIMIT 80001'
            timings, plans, returns, peaks, samples = {}, {}, {}, {}, {}
            storage.explain_sql.update("EXPLAIN "+sql for sql in queries.values())
            with engine.connect() as conn:
                conn.exec_driver_sql('ANALYZE TABLE ' + table)
                mysql_version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
                for label, query in queries.items():
                    times, peak_values = [], []
                    for trial in range(5):
                        tracemalloc.start()
                        start = time.perf_counter()
                        result = conn.execution_options(stream_results=True).exec_driver_sql(query)
                        count = 0
                        while values := result.fetchmany(200):
                            count += len(values)
                        elapsed = (time.perf_counter() - start) * 1000
                        peak_values.append(tracemalloc.get_traced_memory()[1])
                        tracemalloc.stop()
                        times.append(elapsed)
                    samples[label] = dict(milliseconds=times, peak_bytes=peak_values)
                    timings[label] = max(times)
                    returns[label] = count
                    peaks[label] = max(peak_values)
                    plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + query).mappings()]
                allocated = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
                    'WHERE table_schema=:db AND table_name=:t'), {'db': database, 't': table}).scalar_one()
                actual_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM ' + table).scalar_one()
            require(actual_rows == 100000, "容量规模不符")
            measured[kind] = dict(samples=samples, all_rows_verified=100000, rows=actual_rows, import_seconds=import_seconds, allocated_bytes=int(allocated),
                query_ms=timings, query_peak_bytes=peaks, returned=returns, explain=plans,
                repeated_business_dml=repeat_dml, repeated_rows=repeat['row_count'], revised_rows=revision['written_count'])
            print(json.dumps(dict(kind=kind, rows=actual_rows, queries=timings)), flush=True)
        measurements = {kind + '_' + label + '_ms': value for kind, result in measured.items() for label, value in result['query_ms'].items()}
        measurements.update({kind + '_allocated_bytes': result['allocated_bytes'] for kind, result in measured.items()})
        measurements.update({kind + '_import_seconds': result['import_seconds'] for kind, result in measured.items()})
        measurements.update({kind + '_query_peak_bytes': max(result['query_peak_bytes'].values()) for kind, result in measured.items()})
        limits = {key: 2000 if key.endswith('_ms') else 512 * 1024**2 if key.endswith('_allocated_bytes') else
                  120 if key.endswith('_import_seconds') else 32 * 1024**2 for key in measurements}
        report = dict(checked_at=datetime.now(UTC).isoformat(),
            bindings=bindings('performance'), ddl_scopes=ddl_scopes,
            measurements=measurements, limits=limits,
            conditions=dict(platform=platform.platform(), mysql=mysql_version, independent_service=True,
                rows_per_table=100000, cache='first unforced, four warm; maximum conservatively bounds P95',
                source='one normalized live 10000-request row per entity; 5000 securities and 20 synthetic periods'),
            reviewed_tradeoffs='结构化列与证券/日期索引；前十大为汇总而非名单。预告正文随200条页读取，最大文本32768字符。'
                '覆盖以200条流式读取，32MiB预算是单查询Python受测分配。重复/修订测一个完整市场5000行或一个证券20统计日，非全表重复吞吐。'
                '放大实验不代表生产全市场历史覆盖，不能推断冷磁盘延迟或完整进程内存上限。',
            details=measured, representative_rows=seeds)
        report['passed'] = all(measurements[key] <= maximum for key, maximum in limits.items())
        return report
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


def measure_changes(storage):
    root = project_root()
    engine = make_engine(storage.settings)
    database = storage.database
    proof = json.loads((root/'docs/evidence/shareholder-changes-live-2026-10-13.json').read_text('utf8'))
    seed = proof['representative_row']
    kind, table = 'shareholder_changes', 'shareholder_change'
    try:
        ddl = re.search(r'CREATE TABLE IF NOT EXISTS shareholder_change\s*\([\s\S]*?;',
            (root/'sql/schema.sql').read_text('utf8'))[0]
        stamp = datetime.now(UTC)
        names = ('record_key', *columns(kind), 'content_hash', 'version_observed_at')
        insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES('+','.join(':'+k for k in names)+')')
        started, unit = time.perf_counter(), []
        expected = []
        for month in range(20):
            period = f'{2020+month//12}-{month%12+1:02d}-01'
            values = []
            for security in range(5000):
                row = {**seed, 'unified_code': f'{security:06d}.SH', 'data_month': period, 'change_end': period[:8]+'15',
                       'change_start': None, 'announcement_date': period[:8]+'16', 'occurrence': 1}
                values.append({**row, 'record_key': identity(kind, row), 'content_hash': digest(row), 'version_observed_at': mysql_time(stamp)})
                if month == 0:
                    unit.append(row)
            expected.extend([v['record_key'],v['content_hash']] for v in values)
            with engine.begin() as conn:
                for offset in range(0,len(values),300):
                    conn.execute(insert, values[offset:offset+300])
        imported = time.perf_counter()-started
        with engine.connect() as conn:
            verify_table(conn,kind,expected)
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
        timings, returned, plans, peaks, raw_samples = {}, {}, {}, {}, {}
        storage.explain_sql.update("EXPLAIN "+sql for sql in queries.values())
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            for label,query in queries.items():
                samples=[]
                for _ in range(5):
                    started=time.perf_counter()
                    rows=conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter()-started)*1000)
                raw_samples[label]=samples
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
        report=dict(checked_at=datetime.now(UTC).isoformat(),bindings=bindings('changes'),
            ddl_scopes={table:hashlib.sha256(ddl.encode()).hexdigest()},measurements=measurements,limits=limits,
            conditions=dict(platform=platform.platform(),mysql=version,independent_service=True,rows=100000,
                cache='first unforced plus four warm; maximum conservatively bounds P95',source='real normalized early event expanded across 5000 securities and 20 months'),
            reviewed_tradeoffs='事实列与三个业务查询索引；开始日期严格保留月/日精度的VARCHAR(10)，不伪造日。测完整5000行市场重复零DML及单行修订；估计百万行是线性投影而非生产实采或冷盘承诺。',
            details=dict(all_rows_verified=100000,samples=raw_samples,query_ms=timings,returned=returned,explain=plans,repeated_business_dml=0,revised_rows=revision['written_count']),
            passed=all(measurements[k]<=v for k,v in limits.items()))
        return report
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


async def verify(args, family):
    output, report = verification.initial_report(args)
    storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, "timeout须为1～7200秒")
        require(
            args.random_count == 0 and args.seed is None and not args.codes,
            "合成容量不能声明随机实采",
        )
        paths = [
            Path(args.pool_config or default_config_path()).resolve(),
            Path(args.test_mysql_settings).resolve(),
        ]
        report["input_files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text("utf-8"))
        require(isinstance(raw, dict), "测试配置须为JSON对象")
        redactor = Redactor(
            [cfg["mysql"].get("password"), cfg["redis"].get("password"), raw.get("password")]
        )
        settings = test_settings(raw)
        require(family in ('performance','changes'),'未知容量协议')
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg["mysql"])
        report.update(
            subject=family + "_capacity",
            source_sha256=source_digest(project_root()),
            source_server_uuid=source_uuid,
            acceptance_complete=False,
            sample_30_applicable=False,
            sample_30_reason="原五表各100000行或股东变动100000行SQL容量；不请求来源",
        )
        storage = PerformanceCapacityStorage(
            settings, cfg["redis"], report["run_id"], token_hex(32), source_uuid
        )
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name + ".ownership.json")
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(
            before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1]))
        )
        report["storage"] = storage.identity()
        report["environment"] = dict(
            storage.conn.exec_driver_sql(
                "SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,"
                "@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,@@sync_binlog AS sync_binlog,@@log_bin AS log_bin"
            )
            .mappings()
            .one()
        )
        await storage.create_redis()
        storage.seed([], [])
        async with asyncio.timeout(args.timeout):
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure_performance if family=='performance' else measure_changes, storage)))
        report.update(measured)
        report["input_files"].update(
            {str(project_root() / p): sha for p, sha in measured["bindings"].items()}
        )
        require(source_digest(project_root()) == report["source_sha256"], "测量期间源码改变")
        require(
            all(measured["measurements"][k] <= v for k, v in measured["limits"].items()),
            "容量超出冻结原预算",
        )
        require(await storage.client.get(storage.owner_key) == storage.owner, "Redis归属变化")
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report["errors"].append(
            dict(stage="capacity", message=redactor.text(exc, 2048), type=type(exc).__name__)
        )
    finally:
        passed = await verification.complete(output, report, redactor, None, storage, lock, False)
    return passed



def main(family, argv=None):
    # Keep established explicit --sample input; validate before creating resources.
    parser = verification.parser(__doc__)
    parser.add_argument(
        "--test-settings",
        dest="test_mysql_settings",
        help="显式13348 JSON；与--test-mysql-settings同一入口",
    )
    parser.set_defaults(random_count=0, timeout=900)
    # Required validation is shared; support the established explicit capacity spelling.
    values = list(sys.argv[1:] if argv is None else argv)
    values = ["--test-mysql-settings" if x == "--test-settings" else x for x in values]
    args = parser.parse_args(values)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args, family))
    print(("CLEANUP COMPLETE" if args.cleanup_only else "PASS") if passed else "FAIL", flush=True)
    return 0 if passed else 1
