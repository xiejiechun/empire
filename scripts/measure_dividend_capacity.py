"""Full current-source dividend capacity, using shared owned-storage lifecycle."""
import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path
from secrets import token_hex

import source_verification as verification
from dividend_capacity import read_snapshot, seed_history, verify_scope
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, test_settings
from source_verification import require

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor


async def verify(args):
    output, report = verification.initial_report(args)
    manager = storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, 'timeout须为1～7200秒')
        require(args.random_count == 0 and args.seed is None and not args.codes,
                '完整池容量不能声明随机样本；使用默认random-count=0')
        paths = [Path(args.pool_config or default_config_path()).resolve(), Path(args.test_mysql_settings).resolve()]
        report['input_files'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text('utf-8'))
        require(isinstance(raw, dict), '测试连接须为JSON对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw.get('password')])
        test = test_settings(raw)
        lock = acquire_instance_lock()
        snapshot = read_snapshot(cfg)
        report.update(subject='dividends_full_capacity', source_sha256=source_digest(project_root()),
                      input_snapshot=snapshot['identity'], acceptance_complete=False,
                      verification_scope='complete current SQL stock pool and source report-period plan',
                      sample_30_applicable=False, sample_30_reason='容量完整池观测不替代随机30严格实采',
                      routing_policy=dict(use_proxy=True, proxy_fallback=not args.proxy_only))
        binding_paths = [p for p in (project_root() / 'src/empire/features/capital_actions').glob('*.py')]
        binding_paths += [project_root() / p for p in ('sql/schema.sql', 'sql/business-schema.json',
            'scripts/measure_dividend_capacity.py', 'scripts/dividend_capacity.py',
            'scripts/source_test_storage.py', 'scripts/source_verification.py')]
        report['bindings'] = {p.relative_to(project_root()).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in binding_paths}
        report['input_files'].update({str(project_root() / p): checksum for p, checksum in report['bindings'].items()})
        verification.write_report(output, report, redactor)
        storage = PrivateStorage(test, cfg['redis'], report['run_id'], token_hex(32), snapshot['server_uuid'])
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name + '.ownership.json')
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1])))
        report['storage'] = storage.identity()
        report['environment'] = dict(storage.conn.exec_driver_sql(
            'SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,'
            '@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,'
            '@@sync_binlog AS sync_binlog,@@log_bin AS log_bin').mappings().one())
        report['pool_codes'] = [row['unified_code'] for row in snapshot['stocks']]
        await storage.create_redis()
        storage.seed(snapshot['stocks'], snapshot['settings'])
        seed_history(storage, snapshot)
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'], test_cfg['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(test_cfg)
        async with asyncio.timeout(args.timeout):
            await manager.start('pipeline.archive')
            await verify_scope(manager, snapshot, args, report)
        require(await storage.client.get(storage.owner_key) == storage.owner, 'Redis owner已变化')
    except BaseException as exc:
        report['errors'].append(dict(stage='capacity', message=redactor.text(exc, 2048), type=type(exc).__name__))
    finally:
        passed = await verification.complete(output, report, redactor, manager, storage, lock, args.proxy_only)
    return passed


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=7200)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args))
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
