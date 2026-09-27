"""Explicit download-capacity migration; never starts collectors or changes tables."""
import argparse
import json

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.download_settings import (
    DEFAULTS,
    DEVICE_TIERS,
    local_download_options,
    recommended_settings,
    validate_settings,
)
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.routing import site_policy
from empire.plugins.infra.settings import SettingsStore

CAPACITY_KEYS = frozenset(("planned_exit_devices", "max_parallel_downloads"))
PRE_CAPACITY_KEYS = frozenset(DEFAULTS) - CAPACITY_KEYS


def upgrade_download_settings(value):
    """The old nine-key schema is accepted only by this maintenance entry."""
    if isinstance(value, dict) and set(value) == PRE_CAPACITY_KEYS:
        value = {**value, **{key: DEFAULTS[key] for key in CAPACITY_KEYS}}
    return validate_settings(value)


def capacity_plan(rows, groups, *, recommend_devices=None, follow_auto_sites=False):
    original = rows.get(("download", "global"), DEFAULTS)
    settings = upgrade_download_settings(original)
    if recommend_devices is not None:
        settings = recommended_settings(recommend_devices, settings)
    changes = {}
    if ("download", "global") not in rows or original != settings:
        changes[("download", "global")] = settings
    sites = []
    if follow_auto_sites:
        for name, source in sorted(groups.items()):
            base = {key: value for key, value in source.items() if key != "domains"}
            stored = rows.get(("site", name), {})
            if not isinstance(stored, dict) or set(stored) - set(site_policy({})):
                raise ValueError("现有网站配置结构无效，未修改设置")
            policy = site_policy(stored, base)
            if policy["scaling_mode"] == "auto" and policy["max_concurrency"] != 0:
                changes[("site", name)] = {**policy, "max_concurrency": 0}
                sites.append(name)
    return changes, settings, sites


def migrate_database(engine, namespace, groups, *, apply=False,
                     recommend_devices=None, follow_auto_sites=False):
    """All requested setting changes commit together; identical reruns do no DML."""
    store = SettingsStore(None, namespace)
    with engine.begin() as conn:
        result = conn.execute(text("SELECT kind,setting_key,payload FROM app_setting "
            "WHERE namespace=:namespace ORDER BY kind,setting_key FOR UPDATE"),
            {"namespace": namespace})
        rows = {(kind, key): json.loads(value) if isinstance(value, str) else value
                for kind, key, value in result}
        changes, settings, sites = capacity_plan(rows, groups,
            recommend_devices=recommend_devices, follow_auto_sites=follow_auto_sites)
        if apply:
            for (kind, key), value in changes.items():
                store.save_in_transaction(conn, kind, key, value)
            actual = conn.execute(text("SELECT payload FROM app_setting "
                "WHERE namespace=:namespace AND kind='download' AND setting_key='global'"),
                {"namespace": namespace}).scalar_one()
            actual = json.loads(actual) if isinstance(actual, str) else actual
            if actual != settings:
                raise RuntimeError("下载容量配置回读不一致，事务已回滚")
    return {"applied": apply, "changed_settings": [f"{kind}/{key}" for kind, key in changes],
            "follow_global_sites": sites, "recommended_devices": recommend_devices,
            "download_settings": settings,
            "status": "已完成" if apply else "仅核查；使用 --apply 执行"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recommend-devices", type=int, choices=DEVICE_TIERS)
    parser.add_argument("--follow-auto-sites", action="store_true",
        help="明确将现有自动模式站点的并发安全阀改为跟随全局；保留全部间隔及每秒上限")
    args = parser.parse_args()
    cfg, lock, engine = {}, None, None
    try:
        cfg = load_config(args.config)
        local_download_options(cfg.get("http", {}))
        lock = acquire_instance_lock()
        engine = make_engine(cfg["mysql"])
        report = migrate_database(engine, cfg["redis"].get("namespace", "empire:dev"),
            cfg["rate_groups"], apply=args.apply, recommend_devices=args.recommend_devices,
            follow_auto_sites=args.follow_auto_sites)
        print(json.dumps(report, ensure_ascii=False))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None
    finally:
        if engine is not None:
            engine.dispose()
        if lock is not None:
            lock.unlock()


if __name__ == "__main__":
    main()
