"""Original unlock SQL capacity protocols, executed only in guarded owned storage."""
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
from sqlalchemy import event, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.core.time import mysql_time
from empire.features.unlock_industries.collector import UnlockIndustryCollector
from empire.features.unlock_industries.contract import COLUMNS, TABLE
from empire.features.unlock_industries.dataset import UnlockIndustryDataset, read_month
from empire.features.unlock_industries.query import UnlockIndustryDataPlugin
from empire.features.unlock_industries.source import SOURCE_COLUMNS, parse_month
from empire.features.unlocks.collector import UnlockCollector
from empire.features.unlocks.contract import digest, fact_key, group_key
from empire.features.unlocks.dataset import TABLE_COLUMNS, UnlockDataset, read_unit
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.sql_lane import settle


def measure_unlocks(storage, sample):
    root=project_root()
    seed, member=sample['representative_parent'], sample['representative_detail']
    engine=make_engine(storage.settings)
    database=storage.database
    schema=(root/'sql/schema.sql').read_text('utf8')
    ddls={t: re.search(r'CREATE TABLE IF NOT EXISTS '+t+r'\s*\([\s\S]*?;',schema)[0] for t in TABLE_COLUMNS}
    try:
        stamp, unit_p, unit_d = datetime.now(UTC), [], []
        expected_units = {}
        started = time.perf_counter()
        for month in range(100):
            period = f'{2010 + month // 12}-{month % 12 + 1:02d}-15'
            parents, details = [], []
            for security in range(1000):
                p = {**seed, 'unified_code': f'{security:06d}.SH', 'unlock_date': period,
                     'occurrence': 1, 'detail_status': 'present', 'detail_count': 2}
                p['group_key'] = group_key(p)
                p['record_key'] = fact_key(p)
                parents.append(p)
                for holder in range(2):
                    d = {**member, **{k: p[k] for k in ('group_key', 'unified_code', 'unlock_date', 'reason_code')},
                         'holder': member['holder'] + str(holder), 'occurrence': 1}
                    d['record_key'] = fact_key(d, True)
                    details.append(d)
            with engine.begin() as conn:
                for (table, columns), values in zip(TABLE_COLUMNS.items(), (parents, details), strict=True):
                    names = (*columns, 'content_hash', 'version_observed_at')
                    insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
                    for offset in range(0, len(values), 300):
                        conn.execute(insert, [{**r, 'content_hash': digest(r), 'version_observed_at': mysql_time(stamp)}
                                              for r in values[offset:offset + 300]])
            expected_units[period[:7]+'-01|SH'] = digest([
                sorted(parents, key=lambda r:r['record_key']), sorted(details, key=lambda r:r['record_key'])])
            if month == 0:
                unit_p, unit_d = parents, details
        imported = time.perf_counter() - started
        with engine.connect() as conn:
            for unit, expected in expected_units.items():
                require(digest([rows for _,rows in read_unit(conn,unit)]) == expected,
                        '容量全量汇总/明细集合或内容不同')
        unit_p.sort(key=lambda r: r['record_key'])
        unit_d.sort(key=lambda r: r['record_key'])
        envelope = UnlockCollector().envelope('2010-01-01|SH', unit_p, unit_d, dict(page=0, batch_id='capacity'), stamp)
        message_bytes = len(envelope.model_dump_json().encode())
        mapping, dml = UnlockDataset(), []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'restricted_share_unlock' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                dml.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        data = dict(unit='2010-01-01|SH', parents=unit_p, details=unit_d, row_count=3000, archive_state={})
        started = time.perf_counter()
        with engine.begin() as conn:
            repeat = mapping.write(conn, envelope, data)
        repeated = time.perf_counter() - started
        assert repeat['written_count'] == 0 and not dml
        changed = [{**r, 'name': '容量修订'} if i == 0 else r for i, r in enumerate(unit_p)]
        started = time.perf_counter()
        with engine.begin() as conn:
            revision = mapping.write(conn, envelope, {**data, 'parents': changed})
        revised = time.perf_counter() - started
        assert revision['written_count'] == 1
        with engine.connect() as conn:
            stored = [rows for _,rows in read_unit(conn,'2010-01-01|SH')]
            require(stored == [changed,unit_d], '容量修订后关联集合或内容不同')
        event.remove(engine, 'before_cursor_execute', capture)
        queries = dict(page='SELECT * FROM restricted_share_unlock FORCE INDEX(ix_date) ORDER BY unlock_date DESC,unified_code DESC,record_key DESC LIMIT 200',
            security="SELECT * FROM restricted_share_unlock FORCE INDEX(ix_security_date) WHERE unified_code='000000.SH' ORDER BY unlock_date DESC,record_key DESC LIMIT 200",
            detail="SELECT * FROM restricted_share_unlock_detail WHERE group_key='" + unit_p[0]['group_key'] + "' ORDER BY record_key LIMIT 10001",
            month="SELECT * FROM restricted_share_unlock_detail FORCE INDEX(ix_date) WHERE unlock_date>='2010-01-01' AND unlock_date<'2010-02-01' ORDER BY record_key LIMIT 100001",
            range="SELECT unified_code,unlock_date,shares FROM restricted_share_unlock FORCE INDEX(ix_date) WHERE unlock_date BETWEEN '2010-01-01' AND '2010-12-31' ORDER BY unlock_date DESC,unified_code DESC,record_key DESC LIMIT 200")
        storage.explain_sql = {'EXPLAIN '+query for query in queries.values()}
        timings, returned, plans, peaks, sizes, timing_samples = {}, {}, {}, {}, {}, {}
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            for label, query in queries.items():
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    rows = conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter() - started) * 1000)
                timing_samples[label] = samples
                timings[label], returned[label] = max(samples), len(rows)
                sizes[label] = len(json.dumps([list(r) for r in rows], default=str).encode())
                tracemalloc.start()
                conn.exec_driver_sql(query).all()
                peaks[label] = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + query).mappings()]
            for table in TABLE_COLUMNS:
                conn.exec_driver_sql('ANALYZE TABLE ' + table)
            allocation = {r['table_name']: dict(data=int(r['data_length']), indexes=int(r['index_length'])) for r in
                conn.execute(text('SELECT table_name AS table_name,data_length AS data_length,index_length AS index_length '
                    'FROM information_schema.tables WHERE table_schema=:db'), dict(db=database)).mappings()}
        allocated = sum(v['data'] + v['indexes'] for v in allocation.values())
        measurements = {**{k + '_ms': v for k, v in timings.items()}, 'allocated_bytes': allocated,
            'projected_1100000_bytes': allocated * 1100000 // 300000, 'import_seconds': imported,
            'repeat_seconds': repeated, 'revision_seconds': revised, 'message_bytes': message_bytes, 'query_peak_bytes': max(peaks.values())}
        limits = {**{k + '_ms': 5000 if k == 'month' else 100 for k in timings}, 'allocated_bytes': 768 * 1024**2,
            'projected_1100000_bytes': 2 * 1024**3, 'import_seconds': 300, 'repeat_seconds': 5,
            'revision_seconds': 5, 'message_bytes': 524288, 'query_peak_bytes': 32 * 1024**2}
        paths = ['src/empire/features/unlocks/contract.py', 'src/empire/sources/tdx_unlock.py', 'scripts/unlock_capacity.py', 'scripts/source_test_storage.py', 'scripts/source_verification.py', 'src/empire/features/unlocks/dataset.py', 'src/empire/features/unlocks/query.py', 'scripts/measure_unlocks.py']
        report = dict(checked_at=stamp.isoformat(), conditions=dict(platform=platform.platform(), mysql=version,
            isolation='actual UUID verified owned private schema on independent service', cache='first read then five warm reads; maximum reported',
            rows=dict(parents=100000, details=200000), projection='linear 1100000-row planning estimate; not a measured million-detail import'),
            reviewed_tradeoffs='Two typed business tables; request-group shared details; bounded month snapshot and message limits. No stored raw success bodies or duplicated per-parent details.',
            measurements=measurements, limits=limits, allocation=allocation, explain=plans, returned=returned, read_bytes=sizes,
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={t: hashlib.sha256(ddl.encode()).hexdigest() for t, ddl in ddls.items()},
            samples=timing_samples, correctness=dict(all_units_equal=True, units=len(expected_units),
                parent_count=100000, detail_count=200000, repeat_business_dml=0, revision_written=revision['written_count']),
            passed=all(v <= limits[k] for k, v in measurements.items()))
        return report
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()





async def measure_industries(storage, sample_unused):
    sample = json.loads(Path('docs/evidence/unlock-industries-source-2026-10-14.json').read_text('utf8'))
    seed = sample['results'][0]
    raw = dict(ErrorCode=0, ResultSets=[dict(ColName=SOURCE_COLUMNS, Content=seed['sample'], Count=len(seed['sample'])),
                                     dict(ColName=['sstart'], Content=[[seed['month']]], Count=1)])
    seed_row = parse_month(raw, seed['month'][:4] + '-' + seed['month'][4:] + '-01',
                          seed['basis'][:4] + '-' + seed['basis'][4:6] + '-' + seed['basis'][6:])[0]
    engine=make_engine(storage.settings)
    try:
        schema = Path('sql/schema.sql').read_text('utf8')
        ddl = re.search(r'CREATE TABLE IF NOT EXISTS ' + TABLE + r'\s*\([\s\S]*?;', schema)[0]
        names = (*COLUMNS, 'content_hash', 'version_observed_at')
        insert = text(f'INSERT INTO {TABLE}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
        units, stamp, start = {}, datetime.now(UTC), time.perf_counter()
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl.rstrip().removesuffix(';'))
            for index in range(120):
                unit = f'{2010 + index // 12}-{index % 12 + 1:02d}-01'
                rows = [{**seed_row, 'unlock_month': unit, 'industry': f'行业{i:03d}'} for i in range(100)]
                units[unit] = rows
                conn.execute(insert, [{**r, 'content_hash': digest(r), 'version_observed_at': mysql_time(stamp)} for r in rows])
        import_seconds = time.perf_counter() - start
        q = UnlockIndustryDataPlugin()
        async def read(fn, *args):
            return fn(*args)
        q.mysql = SimpleNamespace(read_engine=engine, read=read)
        page_ms, industry_ms, month_ms = [], [], []
        for _ in range(6):
            start = time.perf_counter()
            assert len((await q.list_records())['rows']) == 200
            page_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            assert len((await q.list_records(industry='行业000'))['rows']) == 120
            industry_ms.append((time.perf_counter() - start) * 1000)
            with engine.connect() as conn:
                start = time.perf_counter()
                assert len(read_month(conn, '2010-01-01')[1]) == 100
                month_ms.append((time.perf_counter() - start) * 1000)
        c, mapping = UnlockIndustryCollector(), UnlockIndustryDataset()
        cursor = dict(batch_id='capacity', page=0, basis_date=seed_row['basis_date'])
        envelope = c.envelope(cursor, '2010-01-01', units['2010-01-01'])
        data = mapping.normalize(envelope) | {'archive_state': {}}
        writes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if TABLE in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        with engine.begin() as conn:
            start = time.perf_counter()
            outcome = mapping.write(conn, envelope, data)
            repeat_seconds = time.perf_counter() - start
            assert outcome['written_count'] == 0 and not writes
            changed = [dict(r) for r in data['rows']]
            changed[0]['shares'] = str(int(changed[0]['shares']) + 1)
            newer = c.envelope(cursor, '2010-01-01', changed)
            start = time.perf_counter()
            outcome = mapping.write(conn, newer, mapping.normalize(newer) | {'archive_state': {}})
            revision_seconds = time.perf_counter() - start
            assert outcome['written_count'] == 1
        event.remove(engine, 'before_cursor_execute', capture)
        with engine.connect() as conn:
            for unit, expected in units.items():
                values = changed if unit == '2010-01-01' else expected
                require(read_month(conn,unit)[1] == values, '行业容量全量集合或修订内容不同')
        with engine.connect() as conn:
            assert conn.exec_driver_sql(f'SELECT COUNT(*) FROM {TABLE}').scalar_one() == 12000
            conn.exec_driver_sql(f'ANALYZE TABLE {TABLE}').all()
            conn.exec_driver_sql('SET SESSION information_schema_stats_expiry=0')
            allocated = conn.execute(text('SELECT DATA_LENGTH+INDEX_LENGTH FROM information_schema.tables '
                'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:object_name'), {'object_name': TABLE}).scalar_one()
            mysql_version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            explain_query = f'EXPLAIN SELECT {",".join(COLUMNS)} FROM {TABLE} ' + "WHERE industry='行业000' ORDER BY unlock_month DESC,industry DESC LIMIT 201"
            storage.explain_sql = {explain_query}
            explains = [dict(r) for r in conn.exec_driver_sql(explain_query).mappings()]
        measured = dict(page_ms=max(page_ms), industry_ms=max(industry_ms), month_ms=max(month_ms),
                        allocated_bytes=allocated, import_seconds=import_seconds, repeat_seconds=repeat_seconds,
                        revision_seconds=revision_seconds, message_bytes=len(envelope.model_dump_json().encode()))
        limits = dict(page_ms=100, industry_ms=100, month_ms=100, allocated_bytes=67108864,
                      import_seconds=60, repeat_seconds=5, revision_seconds=5, message_bytes=524288)
        paths = ['src/empire/sources/tdx_unlock.py', 'scripts/unlock_capacity.py', 'scripts/source_test_storage.py', 'scripts/source_verification.py', 'src/empire/features/unlock_industries/contract.py', 'src/empire/features/unlock_industries/source.py',
                 'src/empire/features/unlock_industries/collector.py', 'src/empire/features/unlock_industries/dataset.py',
                 'src/empire/features/unlock_industries/query.py', 'scripts/measure_unlock_industries.py']
        report = dict(checked_at=datetime.now(UTC).isoformat(), conditions=dict(platform=platform.platform(),
            mysql=mysql_version, rows=12000, months=120, cache='six reads including first; maximum reported', isolation='owned UUID database independent service'),
            reviewed_tradeoffs='Typed monthly current rows; old directory months retained; no daily snapshot history; bounded month transactions.',
            measurements=measured, limits=limits, explains=explains, ddl_scopes={TABLE: hashlib.sha256(ddl.encode()).hexdigest()},
            bindings={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
            samples=dict(page_ms=page_ms, industry_ms=industry_ms, month_ms=month_ms),
            correctness=dict(all_units_equal=True, units=120, row_count=12000, repeat_business_dml=0, revision_written=1),
            passed=all(measured[k] <= v for k, v in limits.items()))
        return report
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


def protocol(family):
    require(family in ('unlocks','industries'), '未知解禁容量协议')
    return dict(family=family)

class UnlockCapacityStorage(PrivateStorage):
    def __init__(self,*args,protocol,**kwargs):
        self.protocol=protocol
        self.explain_sql=set()
        super().__init__(*args,**kwargs)

    def guard(self,conn,cursor,statement,parameters,context,executemany):
        tables=set(TABLE_COLUMNS) if self.protocol['family']=='unlocks' else {TABLE}
        # Exact administrative/EXPLAIN statements from the unchanged protocols.
        approved={'ANALYZE TABLE '+table for table in tables}
        if self.protocol['family']=='industries':
            approved.add('SET SESSION information_schema_stats_expiry=0')
        if statement in approved and not parameters and not executemany:
            return super().guard(conn,cursor,'SELECT 1',(),context,False)
        if statement in self.explain_sql and not parameters and not executemany:
            return super().guard(conn,cursor,statement[8:],(),context,False)
        return super().guard(conn,cursor,statement,parameters,context,executemany)

def load_sample(args,family):
    if family=='industries':
        return None
    require(args.sample is not None, '个股解禁容量必须提供本轮实际来源报告')
    path=Path(args.sample).resolve()
    require(path.is_relative_to(project_root()) and path.stat().st_size<=4*1024**2, '样本须项目内有界报告')
    sample=json.loads(path.read_text('utf8'))
    require(sample.get('passed') is True and sample.get('pipeline_verified') is True
            and sample.get('source_sha256')==source_digest(project_root()),'真实样本未核验或源码已改变')
    require(sample.get('subject')=='unlocks' and sample.get('strict_proxy_verified') is True, '必须使用本轮解禁全代理样本')
    return sample

def measure(storage,sample):
    return (measure_unlocks(storage,sample) if storage.protocol['family']=='unlocks'
            else asyncio.run(measure_industries(storage,sample)))

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
        p = protocol(family)
        sample = load_sample(args, family)
        sample_path = (Path(args.sample).resolve() if family == 'unlocks' else
                       project_root()/'docs/evidence/unlock-industries-source-2026-10-14.json')
        sample_sha = hashlib.sha256(sample_path.read_bytes()).hexdigest()
        report['input_files'][str(sample_path)] = sample_sha
        report['reviewed_sample'] = dict(path=str(sample_path.relative_to(project_root())), sha256=sample_sha,
            scope='current full source verification' if family == 'unlocks' else 'unchanged original industry seed')
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg["mysql"])
        report.update(
            subject=family + "_capacity",
            source_sha256=source_digest(project_root()),
            source_server_uuid=source_uuid,
            acceptance_complete=False,
            sample_30_applicable=False,
            sample_30_reason="原100000汇总/200000明细或12000行业行SQL容量；不请求来源",
        )
        storage = UnlockCapacityStorage(
            settings, cfg["redis"], report["run_id"], token_hex(32), source_uuid, protocol=p
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
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure, storage, sample)))
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
    parser.add_argument("--sample")
    parser.set_defaults(random_count=0, timeout=900)
    # Required validation is shared; support the established explicit capacity spelling.
    values = list(sys.argv[1:] if argv is None else argv)
    values = ["--test-mysql-settings" if x == "--test-settings" else x for x in values]
    args = parser.parse_args(values)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args, family))
    print(("CLEANUP COMPLETE" if args.cleanup_only else "PASS") if passed else "FAIL", flush=True)
    return 0 if passed else 1
