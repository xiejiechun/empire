"""One owned-storage lifecycle for bounded real-source verification commands."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

from source_test_storage import PrivateStorage, read_pool, read_server_uuid, test_settings

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.security import split_unified_code
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.plugins.infra.sql_lane import settle

# Keep failed-shutdown producers, ownership locks and guards alive until process
# exit. Losing these references could let a recovery process clean an active run.
_UNSETTLED_RUNS = []


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def select_stocks(stocks: list[dict], count: int, seed: int | None, fixed: list[str]) -> dict:
    require(type(count) is int and 0 <= count <= 100, '随机数量须为 0～100')
    require(count == 0 or type(seed) is int, '随机样本必须显式提供整数 seed')
    pool = sorted(stocks, key=lambda s: s['unified_code'])
    by_code = {row['unified_code']: row for row in pool}
    require(len(by_code) == len(pool) and bool(pool), '抽样池重复或为空')
    for code in by_code:
        split_unified_code(code)
    require(len(pool) >= count, '股票池不足指定随机数量；不得换池凑数')
    require(len(fixed) == len(set(fixed)), '固定反例名单重复')
    require(set(fixed) <= set(by_code), '固定反例必须来自冻结的适用股票池')
    sampled = random.Random(seed).sample([row['unified_code'] for row in pool], count)
    selected = sorted(set(sampled) | set(fixed), key=lambda code: split_unified_code(code))
    require(0 < len(selected) <= 100, '合并随机与固定样本后须有 1～100 只不同股票')
    return dict(algorithm='python.random.Random.sample on sorted unified_code pool', seed=seed,
                pool=pool, pool_digest=digest(pool), random=sampled, fixed=fixed,
                selected=[by_code[code] for code in selected], random_count=count)


def strict_proxy(counts: dict, samples: int) -> bool:
    return (counts.get('proxy_requests', 0) >= samples > 0
            and counts.get('direct_requests', 0) == 0 and counts.get('fallback_requests', 0) == 0)


def write_report(path: Path, report: dict, redactor: Redactor) -> None:
    temporary = path.with_name(path.name + '.' + report['run_id'] + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(redactor.value(report), handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_ownership(path: Path, storage, settings_path: str) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump({**storage.identity(), 'schema': 1, 'owner': storage.owner,
                   'test_settings_path': str(Path(settings_path).resolve())}, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


async def finish(manager, storage, lock, report: dict, redactor: Redactor) -> None:
    cleanup = report['cleanup']

    def failed(stage, exc):
        cleanup[stage] = False
        report['errors'].append(dict(stage=stage, message=redactor.text(exc, 2048)))

    cleanup['shutdown'] = manager is None
    if manager is not None:
        try:
            await asyncio.wait_for(manager.shutdown(), 120)
            require(all(entry.context is None for entry in manager.entries.values()), '仍有插件持有运行上下文')
            cleanup['shutdown'] = True
        except BaseException as exc:
            failed('shutdown', exc)
    if storage is not None:
        # One failure never skips the other independently owned resource.
        if cleanup['shutdown']:
            for name, operation in (('sql', storage.cleanup_sql), ('redis', storage.cleanup_redis)):
                try:
                    if name == 'redis':
                        await asyncio.wait_for(operation(), 60)
                    else:
                        operation()
                    cleanup[name] = True
                except BaseException as exc:
                    failed(name, exc)
        else:
            cleanup.update(sql=False, redis=False, sql_lock=False, connections=False)
        if cleanup['shutdown']:
            try:
                storage.release_sql()
                cleanup['sql_lock'] = True
            except BaseException as exc:
                failed('sql_lock', exc)
            try:
                if storage.client is not None:
                    await storage.client.aclose()
                storage.remove_guard()
                cleanup['connections'] = True
            except BaseException as exc:
                failed('connections', exc)
        report['remaining'] = dict(
            sql='unknown' if getattr(storage, 'sql_unverified', False) else storage.created,
            redis='unknown' if getattr(storage, 'redis_unverified', False) else
            storage.redis_owned or getattr(storage, 'redis_residual', False))
    if lock is not None:
        if cleanup['shutdown']:
            try:
                lock.unlock()
                require(not lock.isLocked(), 'Empire 单实例锁释放失败')
                cleanup['instance_lock'] = True
            except BaseException as exc:
                failed('instance_lock', exc)
        else:
            cleanup['instance_lock'] = False
    if not cleanup['shutdown']:
        _UNSETTLED_RUNS.append((manager, storage, lock))


def final_pass(report: dict, proxy_only: bool) -> bool:
    required = ('shutdown', 'sql', 'redis', 'sql_lock', 'connections', 'instance_lock')
    verified = (report.get('recovery_verified', False) if report.get('mode') == 'cleanup_only'
                else report['pipeline_verified'] and report.get('acceptance_complete', True)
                and (not proxy_only or report['strict_proxy_verified']))
    return (verified and not report['errors']
            and all(report['cleanup'].get(key) is True for key in required)
            )


def initial_report(args, mode='verification'):
    run_id = uuid4().hex
    output = Path(args.output).resolve()
    require(output.is_relative_to(project_root() / 'build'), '验证报告必须位于项目 build 目录')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(run_id=run_id, mode=mode, checked_at=datetime.now(UTC).isoformat(), passed=False,
                  pipeline_verified=False, strict_proxy_verified=False, sample_30_met=False,
                  results={}, errors=[], cleanup=dict(shutdown=False, sql=True, redis=True,
                  sql_lock=True, connections=True, instance_lock=True))
    # An existing evidence file is never overwritten by a new run.
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle)
    return output, report


async def complete(output, report, redactor, manager, storage, lock, proxy_only):
    cleanup_task = asyncio.create_task(finish(manager, storage, lock, report, redactor))
    try:
        await settle(cleanup_task)
    except BaseException as exc:
        report['errors'].append(dict(stage='cleanup_wait', message=redactor.text(exc, 2048)))
    if report.get('mode') != 'cleanup_only' and report.get('source_sha256'):
        try:
            require(source_digest(project_root()) == report['source_sha256'],
                    '关闭/清理期间源输入发生变化；本轮证据失效')
        except BaseException as exc:
            report['errors'].append(dict(stage='final_source_identity', message=redactor.text(exc, 2048)))
    try:
        for filename, expected in report.get('input_files', {}).items():
            require(hashlib.sha256(Path(filename).read_bytes()).hexdigest() == expected,
                    '连接配置文件在验收期间变化；本轮证据失效')
    except BaseException as exc:
        report['errors'].append(dict(stage='final_config_identity', message=redactor.text(exc, 2048)))
    report['passed'] = final_pass(report, proxy_only)
    # PASS is emitted by main only after this atomic durable final write.
    try:
        write_report(output, report, redactor)
    except BaseException as exc:
        print('FAIL final_report: ' + redactor.text(exc, 2048), flush=True)
        return False
    return report['passed']


def recovery_record(path: Path) -> dict:
    target = path.resolve()
    require(target.is_relative_to(project_root() / 'build') and target.stat().st_size <= 65536,
            '恢复记录必须是 build 内有界私有记录')
    value = json.loads(target.read_text(encoding='utf-8'))
    require(isinstance(value, dict) and value.get('schema') == 1, '恢复记录版本无效')
    require(isinstance(value.get('server_uuid'), str) and bool(value['server_uuid']),
            '恢复记录缺少已核实 server_uuid；不能按名称猜测删除')
    return value


def restored_storage(value: dict, test: dict, redis: dict, production_uuid: str):
    storage = PrivateStorage(test, redis, value['run_id'], value['owner'], production_uuid)
    for key in ('database', 'namespace', 'owner_sha256'):
        require(value.get(key) == storage.identity()[key], '恢复记录派生身份不匹配：' + key)
    return storage


async def recover(args) -> bool:
    output, report = initial_report(args, 'cleanup_only')
    redactor, storage, lock = Redactor(), None, None
    try:
        require(bool(args.run_state), 'cleanup-only 必须提供既有 run-state')
        config_path = Path(args.pool_config or default_config_path()).resolve()
        test_path = Path(args.test_mysql_settings).resolve()
        report['input_files'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (config_path, test_path)}
        cfg = load_config(config_path)
        redactor = Redactor.from_config(cfg)
        raw_test = json.loads(test_path.read_text(encoding='utf-8'))
        require(isinstance(raw_test, dict), '测试连接文件必须是 JSON 对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw_test.get('password')])
        value = recovery_record(Path(args.run_state))
        redactor = Redactor([*redactor.secrets, value.get('owner')])
        lock = acquire_instance_lock()
        storage = restored_storage(value, test_settings(raw_test), cfg['redis'], read_server_uuid(cfg['mysql']))
        report['storage'] = {key: value[key] for key in ('run_id', 'database', 'namespace', 'server_uuid', 'owner_sha256')}
        # Independent identity checks preserve an original error and still allow
        # the other exactly owned resource to be recovered safely.
        for name in ('sql', 'redis'):
            try:
                if name == 'sql':
                    storage.attach_sql(value['server_uuid'])
                else:
                    await storage.attach_redis()
            except BaseException as exc:
                report['errors'].append(dict(stage='recover_' + name, message=redactor.text(exc, 2048)))
        report['recovery_verified'] = not report['errors']
    except BaseException as exc:
        report['errors'].append(dict(stage='recovery', message=redactor.text(exc, 2048), type=type(exc).__name__))
    finally:
        passed = await complete(output, report, redactor, None, storage, lock, False)
    return passed


async def verify(args, verify_scope, *, subject='source', fixed_codes=(), minimum_random=0,
                 require_proxy=False, non_stock_scope=None, prepare_scope=None) -> bool:
    output, report = initial_report(args)
    redactor, manager, storage, lock = Redactor(), None, None, None
    try:
        require(type(args.random_count) is int and args.random_count >= minimum_random,
                f'本范围至少需要随机 {minimum_random} 只不同股票；固定反例不能代替随机样本')
        require(not require_proxy or args.proxy_only, '本次实采必须全部使用共享代理')
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, 'timeout 须为 1～7200 秒')
        require(len(args.codes) == len(set(args.codes)), '固定反例名单重复')
        if non_stock_scope is not None:
            require(isinstance(non_stock_scope, dict) and set(non_stock_scope) == {'unit', 'reason', 'fixed'}
                    and all(isinstance(non_stock_scope[key], str) and non_stock_scope[key].strip()
                            for key in ('unit', 'reason'))
                    and isinstance(non_stock_scope['fixed'], list)
                    and all(isinstance(code, str) and code for code in non_stock_scope['fixed'])
                    and len(set(non_stock_scope['fixed'])) == len(non_stock_scope['fixed']), '非股票范围声明无效')
            require(args.random_count == 0 and args.seed is None and not args.codes and not fixed_codes
                    and minimum_random == 0, '非股票验证不得声明股票随机样本或固定股票名单')
        config_path = Path(args.pool_config or default_config_path()).resolve()
        test_path = Path(args.test_mysql_settings).resolve()
        report['input_files'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (config_path, test_path)}
        # Passing an explicit path prevents load_config from creating a template.
        cfg = load_config(config_path)
        redactor = Redactor.from_config(cfg)
        raw_test = json.loads(test_path.read_text(encoding='utf-8'))
        require(isinstance(raw_test, dict), '测试连接文件必须是 JSON 对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw_test.get('password')])
        test = test_settings(raw_test)
        lock = acquire_instance_lock()
        snapshot = read_pool(cfg)
        fixed = list(dict.fromkeys((*fixed_codes, *args.codes)))
        selection = (select_stocks(snapshot['stocks'], args.random_count, args.seed, fixed)
                     if non_stock_scope is None else dict(selected=[], random=[], fixed=[], random_count=0,
                                                          non_stock_scope=copy.deepcopy(non_stock_scope)))
        report.update(subject=subject, selection=selection, source_sha256=source_digest(project_root()),
                      source_server_uuid=snapshot['server_uuid'],
                      verification_scope='proxy_pipeline' if args.proxy_only else 'development_pipeline',
                      routing_policy=dict(use_proxy=True, proxy_fallback=not args.proxy_only),
                      sample_30_applicable=non_stock_scope is None and len(snapshot['stocks']) >= 30,
                      policy_snapshot_digest=digest(snapshot['settings']), acceptance_complete=False)
        write_report(output, report, redactor)
        # Reviewed source dependencies must be read before the global private-SQL
        # guard is installed. This hook cannot relax or remove that guard.
        if prepare_scope is not None:
            prepare_scope(selection, args, report)
        storage = PrivateStorage(test, cfg['redis'], report['run_id'], token_hex(32), snapshot['server_uuid'])
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name + '.ownership.json')
        with ownership.open('x', encoding='utf-8') as handle:
            json.dump({**storage.identity(), 'schema': 1, 'owner': storage.owner,
                       'test_settings_path': str(test_path)}, handle, indent=2)
        storage.create_sql(before_create=lambda: write_ownership(ownership, storage, str(test_path)))
        report['storage'] = storage.identity()
        await storage.create_redis()
        storage.seed(selection['selected'], snapshot['settings'])
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'] = storage.settings
        test_cfg['redis']['namespace'] = storage.namespace
        manager = build_manager(test_cfg)
        async with asyncio.timeout(args.timeout):
            await manager.start('pipeline.archive')
            await verify_scope(manager, selection, args, report)
        require(await storage.client.get(storage.owner_key) == storage.owner, 'Redis owner 丢失，证据中断')
        require(source_digest(project_root()) == report['source_sha256'], '源输入发生变化；本轮证据失效')
        results = report['results']
        require(bool(results), '验证未返回任何业务结果')
        report['pipeline_verified'] = all(row.get('pipeline_verified') is True for row in results.values())
        report['strict_proxy_verified'] = all(row.get('strict_proxy_verified') is True for row in results.values())
        report['acceptance_complete'] = all(row.get('acceptance_complete', True) for row in results.values())
        report['sample_30_met'] = (report['sample_30_applicable'] and report['strict_proxy_verified'] and args.random_count >= 30
            and all(row.get('random_samples_complete', row.get('pipeline_verified')) is True
                    for row in results.values()))
    except BaseException as exc:
        report['errors'].append(dict(stage='verification', message=redactor.text(exc, 2048),
                                     type=type(exc).__name__))
    finally:
        passed = await complete(output, report, redactor, manager, storage, lock, args.proxy_only)
    return passed


def parser(description: str) -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=description)
    value.add_argument('--pool-config', help='只读正式股票池/站点设置及共享代理目录连接')
    value.add_argument('--test-mysql-settings', required=True, help='显式13348独立MySQL JSON连接配置')
    value.add_argument('--output', required=True, help='build内的新报告文件；禁止覆盖已有报告')
    value.add_argument('--random-count', type=int, default=30)
    value.add_argument('--seed', type=int)
    value.add_argument('--codes', nargs='*', default=[], help='额外固定统一证券代码，例如600000.SH')
    value.add_argument('--proxy-only', action='store_true', help='禁止直连回退；严格代理实采必须提供')
    value.add_argument('--timeout', type=int, default=900)
    value.add_argument('--cleanup-only', action='store_true', help='仅清理已记录且能验证归属的私有资源')
    value.add_argument('--run-state', help='原报告旁的.ownership.json；只读且不覆盖')
    return value
