"""Explicit three-task retirement; preserve business rows and rebuild shared proof."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.collection.control import validate_policy
from empire.plugins.datasets.holders import HolderDataset
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.settings import SettingsStore
from empire.plugins.pipeline.fingerprints import FingerprintCache

OLD = ('ths-top-holders', 'ths-float-holders', 'ths-bond-holders')
NEW = 'ths-holders'


def choose_policy(saved, default):
    if NEW in saved:
        return validate_policy(saved[NEW])
    old = [validate_policy(saved[key]) for key in OLD if key in saved]
    if old and any(value != old[0] for value in old[1:]):
        raise ValueError('旧三个任务配置不同；须显式保存新的统一任务配置后再迁移')
    return old[0] if old else validate_policy(default)


def business_inventory(conn):
    result = {}
    for table, columns in (
            ('holder_report', ('report_key', 'content_hash', 'version_observed_at', 'member_count', 'exit_count')),
            ('holder_member', ('report_key', 'member_group', 'seq', 'holder_name', 'holder_id', 'quantity',
                'quantity_scale', 'quantity_decimals', 'ratio', 'change_quantity', 'change_label',
                'actual_change', 'share_type', 'pledge_ratio', 'pledge_status'))):
        expression = ','.join("COALESCE(CAST(" + key + " AS CHAR),'NULL')" for key in columns)
        row = conn.execute(text('SELECT COUNT(*) AS n,COALESCE(SUM(CRC32(CONCAT_WS(CHAR(31),'
            + expression + '))),0) AS checksum FROM ' + table)).mappings().one()
        result[table] = {key: str(value) for key, value in row.items()}
    return result


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    prefix = cfg['redis'].get('namespace', 'empire')
    report = dict(checked_at=datetime.now(UTC).isoformat(), applied=False, retired=list(OLD), new=NEW)
    try:
        report['pending'] = await client.xlen(prefix + ':ingest')
        if args.apply and report['pending']:
            raise ValueError('待归档非零，拒绝合并任务')
        definition = build_manager(cfg).entries['collection.control'].plugin.definitions[NEW]
        default = definition.default_schedule.policy(dict(enabled=False, mode='manual',
            interval_seconds=definition.interval_seconds, daily_time='18:00', request_retries=2))
        with engine.connect() as conn:
            if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('已有维护操作，拒绝并发')
            conn.commit()
            try:
                with conn.begin():
                    saved = {key: json.loads(value) if isinstance(value, str) else value for key, value in
                        conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns AND kind='task' FOR UPDATE"), {'ns': prefix})}
                    report['policy'] = choose_policy(saved, default)
                    report['before'] = business_inventory(conn)
                    if args.apply:
                        SettingsStore(SimpleNamespace(engine=engine), prefix).save_in_transaction(conn, 'task', NEW, report['policy'])
                        for key in OLD:
                            conn.execute(text("DELETE FROM app_setting WHERE namespace=:ns AND kind='task' AND setting_key=:key"), {'ns': prefix, 'key': key})
                            conn.execute(text('DELETE FROM collection_state WHERE namespace=:ns AND project_id=:key'), {'ns': prefix, 'key': key})
                    report['after'] = business_inventory(conn)
                    if report['before'] != report['after']:
                        raise ValueError('持有人业务核对不符，回滚迁移')
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        if args.apply:
            cache = FingerprintCache(SimpleNamespace(client=client, prefix=prefix), cfg.get('archive', {}),
                                     lambda _: HolderDataset.FINGERPRINT_VERSION)
            for kind in ('top_holders', 'float_holders', 'bond_holders'):
                await cache.invalidate('ths_' + kind, 'ths')
            await cache.invalidate('ths_holders', 'ths')
            await client.delete(*(prefix + ':checkpoint:' + key + '-v1' for key in OLD),
                                *(prefix + ':archive:progress:' + key + '-v1' for key in OLD))
            control_key = prefix + ':collection:control:v1'
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(control_key)
                raw = await pipe.get(control_key)
                if raw:
                    state = json.loads(raw)
                    for key in OLD:
                        state.get('jobs', {}).pop(key, None)
                    pipe.multi()
                    pipe.set(control_key, json.dumps(state, ensure_ascii=False))
                    await pipe.execute()
            report.update(applied=True, business_preserved=True, proof_rebuild_required=True,
                          old_runtime_and_errors_preserved=True)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('PASS holder task migration' if args.apply else 'PASS holder task migration preflight')
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', default='docs/evidence/ths-holders-task-migration-2026-10-13.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
