"""Frozen 1000-row BSE pipeline capacity protocol in UUID-owned private storage."""
import asyncio
import copy
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from secrets import token_hex
from time import perf_counter
from uuid import uuid4

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, read_server_uuid, test_settings
from source_verification import require
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.features.security_aliases import dataset
from empire.features.security_aliases.contract import URL
from empire.plugins.infra.schema_manifest import shape

READ_SQL = ('SELECT legacy_code,unified_code,name,listing_date FROM security_code_alias '
            'ORDER BY legacy_code LIMIT 1000')
EXPLAIN_SQL = "EXPLAIN SELECT * FROM security_code_alias WHERE unified_code='920149.BJ'"
ANALYZE_SQL = 'ANALYZE TABLE security_code_alias'
BINDINGS = (
    'scripts/measure_bse_capacity.py', 'scripts/source_test_storage.py', 'scripts/source_verification.py',
    'src/empire/features/security_aliases/contract.py', 'src/empire/features/security_aliases/dataset.py',
    'src/empire/features/security_aliases/bundle.py', 'scripts/import_bse_code_mapping.py',
    'sql/business-schema.json', 'src/empire/contracts/business_schema.py',
)


class BseCapacityStorage(PrivateStorage):
    def guard(self, conn, cursor, statement, parameters, context, executemany):
        if statement in (EXPLAIN_SQL, ANALYZE_SQL) and not parameters and not executemany:
            # The inherited guard reads actual @@server_uuid and DATABASE() on
            # this very session before permitting these two literal statements.
            super().guard(conn, cursor, 'SELECT 1', (), context, False)
            return
        super().guard(conn, cursor, statement, parameters, context, executemany)


def fixed_rows():
    return [dict(legacy_code=str(830000+i), unified_code=f'920{i:03d}.BJ',
                 name=f'证券{i}', listing_date='2020-07-27') for i in range(1000)]


def make_event(rows):
    batch = uuid4().hex
    return make_envelope(source='bse', dataset='bse.code_mapping.complete', job_key=dataset.JOB,
        run_id=batch, batch_id=batch, business_key='official-table',
        payload=dict(page=1, rows=rows, source_count=len(rows), source_url=URL))


async def publish(manager, envelope):
    ingest = manager.registry.get('ingest.publish')
    archive = manager.registry.get('archive.worker')
    checkpoint = await ingest.checkpoint(dataset.JOB)
    await ingest.publish_page([envelope], job_key=dataset.JOB,
        expected_revision=checkpoint['revision'], cursor=dict(batch_id=envelope.batch_id, page=1))
    await archive.flush()


def read_rows(mysql):
    with mysql.read_engine.connect() as conn:
        stored = [dict(row) for row in conn.execute(text(READ_SQL)).mappings()]
    for row in stored:
        row['listing_date'] = row['listing_date'].isoformat()
    return stored


def inspect(mysql, database):
    with mysql.engine.connect() as conn:
        plan = [dict(row) for row in conn.exec_driver_sql(EXPLAIN_SQL).mappings()]
        analyzed = [dict(row) for row in conn.exec_driver_sql(ANALYZE_SQL).mappings()]
        allocated = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
            'WHERE table_schema=:db AND table_name=:object_name'),
            dict(db=database, object_name='security_code_alias')).scalar_one()
        return dict(explain=plan, analyze=analyzed, allocated_bytes=int(allocated),
                    shape=shape(conn, 'security_code_alias'))


async def measure(manager, storage):
    rows = fixed_rows()
    envelope = make_event(rows)
    normalized = dataset.normalize(envelope)
    require(normalized['rows'] == rows and normalized['row_count'] == 1000, '规范集合或内容不同')
    # Frozen protocol starts immediately before checkpoint, includes publish
    # and shared archive.flush, never times a direct dataset write.
    started = perf_counter()
    await publish(manager, envelope)
    imported_ms = (perf_counter()-started)*1000
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '本轮待归档或隔离非空')
    mysql = manager.registry.get('mysql.store')
    # Match the old single-query timing, excluding lane admission and pool
    # setup; exactly one ordered LIMIT 1000 business query is measured.
    def timed_read():
        with mysql.read_engine.connect() as conn:
            started = perf_counter()
            values = [dict(row) for row in conn.execute(text(READ_SQL)).mappings()]
            elapsed = (perf_counter()-started)*1000
        for row in values:
            row['listing_date'] = row['listing_date'].isoformat()
        return values, elapsed
    stored, read_ms = await mysql.read(timed_read)
    require(stored == rows, '1000行SQL完整集合或内容不同')
    metadata = await mysql.control(inspect, mysql, storage.database)
    require(metadata['explain'] and metadata['explain'][0]['key'] == 'ux_alias_security', '正式点查未使用唯一索引')
    require(all(row['Msg_type'] == 'status' and row['Msg_text'] == 'OK' for row in metadata['analyze']),
            'ANALYZE未成功')
    measurements = dict(import_ms=imported_ms, read_ms=read_ms, allocated_bytes=metadata['allocated_bytes'])
    limits = dict(import_ms=2000, read_ms=100, allocated_bytes=1048576)
    root = project_root()
    ddl = re.search(r'CREATE TABLE IF NOT EXISTS security_code_alias\s*\([\s\S]*?;',
                    (root/'sql/schema.sql').read_text('utf-8')).group()
    return dict(measurements=measurements, limits=limits,
        bindings={p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in BINDINGS},
        ddl_scopes={'security_code_alias': hashlib.sha256(ddl.encode()).hexdigest()},
        conditions=dict(platform=platform.platform(), python=platform.python_version(), rows=1000,
            synthetic=True, network_requests=0, pipeline='checkpoint -> publish_page -> archive.flush',
            query=READ_SQL, read_count=1, cache='unforced first query; no cold-cache reset'),
        reviewed_tradeoffs='固定1000项及有界整表读取；一个主键和一个唯一索引，关系增量保留历史。单次首读未强制冷缓存，不推断生产网络吞吐或官方完整性。',
        correctness=dict(normalized_equal=True, source_sql_equal=True, row_count=len(stored), pending=pending,
            expected_digest=verification.digest(rows), actual_digest=verification.digest(stored)),
        **metadata)


async def verify(args):
    output, report = verification.initial_report(args)
    storage = manager = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, 'timeout须为1～7200秒')
        require(args.random_count == 0 and args.seed is None and not args.codes, '合成容量不能声明股票实采')
        paths = [Path(args.pool_config or default_config_path()).resolve(), Path(args.test_mysql_settings).resolve()]
        report['input_files'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text('utf-8'))
        require(isinstance(raw, dict), '测试连接须为JSON对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw.get('password')])
        test = test_settings(raw)
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg['mysql'])
        report.update(subject='bse_mapping_capacity', source_sha256=source_digest(project_root()),
            source_server_uuid=source_uuid, acceptance_complete=False, sample_30_applicable=False,
            sample_30_reason='1000行固定合成容量，不请求官方来源，不替代真实完整表验收')
        storage = BseCapacityStorage(test, cfg['redis'], report['run_id'], token_hex(32), source_uuid)
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
        private_cfg = copy.deepcopy(cfg)
        private_cfg['mysql'] = storage.settings
        private_cfg['redis']['namespace'] = storage.namespace
        manager = build_manager(private_cfg)
        async with asyncio.timeout(args.timeout):
            await manager.start('pipeline.ingest')
            measured = await measure(manager, storage)
        report.update(measured)
        report['input_files'].update({str(project_root()/p): sha for p, sha in measured['bindings'].items()})
        require(all(measured['measurements'][key] <= limit for key, limit in measured['limits'].items()),
                '容量超出冻结预算')
        require(await storage.client.get(storage.owner_key) == storage.owner, 'Redis归属变化')
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report['errors'].append(dict(stage='capacity', message=redactor.text(exc, 2048), type=type(exc).__name__))
    finally:
        passed = await verification.complete(output, report, redactor, manager, storage, lock, False)
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
