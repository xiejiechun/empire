"""Explicit, resumable replacement of retired HTTP index datasets; never startup DDL."""
import argparse
import asyncio
import hashlib
import json
from contextlib import AsyncExitStack
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.features.yuanhang_indices.contract import (
    CATALOG_PROJECT,
    MEMBER_PROJECT,
    PRICE_PROJECT,
    digest,
)
from empire.plugins.collection.control import validate_policy
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes
from empire.plugins.infra.settings import SettingsStore

if __package__:
    from .create_name_change_schema import ddl
else:
    from create_name_change_schema import ddl

OLD_TABLES = ('stock_index_member', 'stock_index', 'index_daily_price', 'index_price_year')
NEW_TABLES = ('yuanhang_index', 'ths_index_member_state', 'ths_index_member',
              'yuanhang_index_daily_price', 'yuanhang_index_price_year')
OLD_PROJECTS = ('ths-indices', 'ths-index-prices')
POLICY_MAP = {CATALOG_PROJECT: 'ths-indices', MEMBER_PROJECT: 'ths-indices', PRICE_PROJECT: 'ths-index-prices'}


def policies(previous):
    """Saved legal new policies win; retain old settings as disabled archive records."""
    result = dict(previous)
    for new, old in POLICY_MAP.items():
        if new in result:
            validate_policy(result[new])
        elif old in previous:
            result[new] = validate_policy(previous[old])
    for old in OLD_PROJECTS:
        if old in previous:
            result[old] = {**validate_policy(previous[old]), 'enabled': False, 'archived': True}
    return result


def snapshot(conn, namespace):
    targets = set(OLD_TABLES) | set(NEW_TABLES)
    result = {}
    for table in inspect(conn).get_table_names():
        if table not in targets:
            result[table] = dict(count=conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}`').scalar_one(),
                shape_hash=digest(conn.exec_driver_sql(f'SHOW CREATE TABLE `{table}`').first()[1]))
    # Exclude only the precisely authorized project-state and task-policy rows.
    states = [list(r) for r in conn.execute(text('SELECT * FROM collection_state ORDER BY namespace,project_id'))
        if not (r.namespace == namespace and r.project_id in OLD_PROJECTS)]
    settings = [list(r) for r in conn.execute(text('SELECT * FROM app_setting ORDER BY namespace,kind,setting_key'))
        if not (r.namespace == namespace and r.kind == 'task' and r.setting_key in (*OLD_PROJECTS, *POLICY_MAP))]
    result['collection_state'].pop('count')
    result['app_setting'].pop('count')
    result['unrelated_states_hash'] = digest([[str(v) for v in r] for r in states])
    result['unrelated_settings_hash'] = digest([[str(v) for v in r] for r in settings])
    return result


def identity(conn, cfg):
    return dict(conn.exec_driver_sql('SELECT @@server_uuid AS server_uuid,DATABASE() AS database_name,@@port AS port').mappings().one(),
        namespace=cfg['redis']['namespace'], schema_sha256=hashlib.sha256((project_root()/'sql/schema.sql').read_bytes()).hexdigest())


async def switch(cfg, args):
    path = Path(args.report).resolve()
    if path.exists():
        raise FileExistsError('维护报告必须使用新路径，不覆盖既有证据')
    path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(applied=False, completed_steps=[], error=None)
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf8')
    resources = AsyncExitStack()
    namespace, held, conn = cfg['redis']['namespace'], False, None
    try:
        if args.apply:
            lock = acquire_instance_lock()
            resources.callback(lock.unlock)
        engine = make_engine(cfg['mysql'])
        resources.callback(engine.dispose)
        client = create_client(cfg['redis'])
        resources.push_async_callback(client.aclose)
        conn = resources.enter_context(engine.connect())
        report.update(identity=identity(conn, cfg), queue=await client.xlen(namespace+':ingest'),
            ddl_sha256={t: digest(ddl(t)) for t in NEW_TABLES}, old_tables={}, new_tables=list(NEW_TABLES))
        existing = set(inspect(conn).get_table_names())
        for table in OLD_TABLES:
            report['old_tables'][table] = conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}`').scalar_one() if table in existing else None
        raw = conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns AND kind='task'"), dict(ns=namespace))
        previous = {r[0]: json.loads(r[1]) if isinstance(r[1], str) else r[1] for r in raw}
        migrated = policies(previous)
        report['policy_changes'] = {key: value for key, value in migrated.items() if previous.get(key) != value}
        report['before'] = snapshot(conn, namespace)
        save()
        if not args.apply:
            return report
        if not args.plan:
            raise ValueError('apply需要已核实的只读plan报告')
        planned = json.loads(Path(args.plan).read_text('utf8'))
        if planned['identity'] != report['identity'] or planned['ddl_sha256'] != report['ddl_sha256']:
            raise ValueError('计划与实际数据库身份、命名空间或DDL不一致')
        if report['queue']:
            raise ValueError('待归档消息未清零，拒绝退役旧schema')
        if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
            raise ValueError('已有数据库维护，拒绝并发')
        held = True
        validate_shapes(conn, [t for t in NEW_TABLES if t in existing])
        for table in NEW_TABLES:
            conn.exec_driver_sql(ddl(table))
            conn.commit()
            report['completed_steps'].append('create:'+table)
            save()
        validate_shapes(conn, NEW_TABLES)
        # Delete only the retired sources' disposable summaries/checkpoints;
        # do not clear operational records, unrelated keys or any Stream.
        keys = [namespace+':archive:fingerprints:v1:'+fp+':ths'+suffix
            for fp in ('ths_indices_v1', 'ths_index_prices_v1') for suffix in ('', ':expiry')]
        keys += [namespace+prefix+old+'-v1' for old in OLD_PROJECTS
            for prefix in (':checkpoint:', ':archive:progress:')]
        await client.delete(*keys)
        report['completed_steps'].append('invalidate-retired-proofs')
        save()
        # Existing new datasets are preserved; old HTTP facts are not copied.
        for table in OLD_TABLES:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS `{table}`')
            conn.commit()
            report['completed_steps'].append('drop:'+table)
            save()
        for key, value in report['policy_changes'].items():
            SettingsStore(None, namespace).save_in_transaction(conn, 'task', key, value)
        for old in OLD_PROJECTS:
            conn.execute(text('DELETE FROM collection_state WHERE namespace=:ns AND project_id=:project'), dict(ns=namespace, project=old))
        conn.commit()
        control_key = namespace+':collection:control:v1'
        raw_control = await client.get(control_key)
        if raw_control:
            control = json.loads(raw_control)
            for old in OLD_PROJECTS:
                if old in control.get('jobs', {}):
                    job = control['jobs'][old]
                    job.update(policy={**validate_policy(job['policy']), 'enabled': False, 'archived': True},
                        next_due=None, active=None, last_status='archived')
            for new in POLICY_MAP:
                # Preserve existing new runtime state. Missing new jobs are
                # created from their durable policy by the normal controller.
                if new in control.get('jobs', {}) and new in migrated:
                    control['jobs'][new]['policy'] = migrated[new]
            await client.set(control_key, json.dumps(control, ensure_ascii=False))
        report['after'] = snapshot(conn, namespace)
        if report['after'] != report['before']:
            raise ValueError('无关业务数量、结构、状态或配置变化；按报告诊断，不宣称成功')
        if await client.xlen(namespace+':ingest'):
            raise ValueError('维护后队列非零')
        report.update(applied=True, unrelated_business_unchanged=True,
            recovery='DDL按completed_steps逐项隐式提交；同一身份和DDL可重新预检后重入。旧表删除后不声称可事务回滚，不覆盖新表业务。')
        save()
        return report
    except BaseException as exc:
        report['error'] = type(exc).__name__
        save()
        raise
    finally:
        try:
            if held and conn is not None:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        finally:
            await resources.aclose()



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--report', required=True)
    parser.add_argument('--plan')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cfg = load_config(args.config)
    try:
        report = asyncio.run(switch(cfg, args))
        print(json.dumps(dict(applied=report['applied'], queue=report['queue'], report=args.report)))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None


if __name__ == '__main__':
    main()
