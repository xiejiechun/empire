"""Explicitly apply seven recommended schedules; preserve enabled and routing choices."""
import argparse
import json

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.task import HISTORICAL_DAY_DEFAULTS
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.collection.control import validate_policy
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.settings import SettingsStore


def task_plan(rows):
    result = {}
    for kind in PRODUCTS:
        ident = project(kind)
        old = rows.get(ident, dict(enabled=False, mode='manual', interval_seconds=86400,
                                  daily_time='18:00', request_retries=2))
        result[ident] = validate_policy(HISTORICAL_DAY_DEFAULTS.policy(validate_policy(old)))
    return result


def migrate_database(engine, namespace, *, apply=False):
    store = SettingsStore(None, namespace)
    with engine.begin() as conn:
        rows = {key: json.loads(value) if isinstance(value, str) else value for key, value in
                conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns "
                    "AND kind='task' FOR UPDATE"), dict(ns=namespace))}
        plan = task_plan(rows)
        changed = [key for key, value in plan.items() if rows.get(key) != value]
        if apply:
            for key in changed:
                store.save_in_transaction(conn, 'task', key, plan[key])
            actual = {key: json.loads(value) if isinstance(value, str) else value for key, value in
                      conn.execute(text("SELECT setting_key,payload FROM app_setting WHERE namespace=:ns "
                          "AND kind='task'"), dict(ns=namespace))}
            if any(actual.get(key) != value for key, value in plan.items()):
                raise RuntimeError('七项任务配置回读不一致，事务回滚')
    return dict(applied=apply, changed=changed, policies=plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cfg, engine, lock = {}, None, None
    try:
        cfg = load_config(args.config)
        lock = acquire_instance_lock()
        engine = make_engine(cfg['mysql'])
        print(json.dumps(migrate_database(engine, cfg['redis'].get('namespace', 'empire'),
                                          apply=args.apply), ensure_ascii=False))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None
    finally:
        if engine is not None:
            engine.dispose()
        if lock is not None:
            lock.unlock()


if __name__ == '__main__':
    main()
