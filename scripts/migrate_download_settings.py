"""Explicit, repeatable migration of legacy TOML download limits into MySQL."""
import argparse
import asyncio
import copy
import json
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.contracts.download_settings import DEFAULTS, LEGACY_KEYS, validate_settings
from empire.core.config import default_config_path
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.infra.settings import SettingsStore


def migration_plan(source):
    """Only remove simple assignment lines; semantic verification is mandatory."""
    original = tomllib.loads(source)
    http = original.get("http", {})
    if not isinstance(http, dict):
        raise ValueError("http 配置必须是表，未修改文件")
    keys = sorted(set(http) & set(LEGACY_KEYS))
    if not keys:
        return original, source, None, keys
    values = validate_settings({**DEFAULTS, **{key: http[key] for key in keys}})
    rewritten, removed, in_http = [], set(), False
    key_pattern = "|".join(re.escape(key) for key in keys)
    assignment = re.compile(
        rf"^(?P<indent>[ \t]*)(?P<key>{key_pattern})[ \t]*=[ \t]*"
        r"[+-]?[0-9][0-9_]*[ \t]*(?P<comment>\#.*)?(?P<ending>\r?\n)?$")
    for line in source.splitlines(keepends=True):
        if re.match(r"^[ \t]*\[", line):
            in_http = bool(re.fullmatch(r"[ \t]*\[http\][ \t]*(?:\#.*)?(?:\r?\n)?", line))
        match = assignment.fullmatch(line) if in_http else None
        if match:
            removed.add(match["key"])
            if match["comment"]:
                rewritten.append(match["indent"] + match["comment"] + (match["ending"] or ""))
        else:
            rewritten.append(line)
    result = "".join(rewritten)
    expected = copy.deepcopy(original)
    for key in keys:
        del expected["http"][key]
    if removed != set(keys) or tomllib.loads(result) != expected:
        raise ValueError("旧下载配置使用复杂 TOML 写法，无法安全自动移除；未修改配置或 MySQL")
    return original, result, values, keys


def connection_config(config):
    result = copy.deepcopy(config)
    for section in ("redis", "mysql"):
        result.setdefault(section, {})
        override = os.environ.get(f"EMPIRE_{section.upper()}_PASSWORD")
        if override is not None:
            result[section]["password"] = override
    namespace = result["redis"].get("namespace", "empire:dev")
    if not re.fullmatch(r"empire:[a-zA-Z0-9:_-]+", namespace):
        raise ValueError("Redis namespace 格式无效")
    return result


def replace_config(path, original, replacement):
    """Write only after SQL success, preserving the original on staging failures."""
    if path.is_symlink() or path.read_bytes() != original:
        raise RuntimeError("SQL 已确认配置，但本地文件在迁移期间变化；未覆盖文件，可核对后重新执行")
    descriptor, temporary = tempfile.mkstemp(prefix=".download-settings-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(replacement.encode("utf-8"))
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if path.is_symlink() or path.read_bytes() != original:
            raise RuntimeError("SQL 已确认配置，但本地文件在迁移期间变化；未覆盖文件，可重新执行")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def migrate(path, *, apply=False):
    path = Path(path)
    lock = acquire_instance_lock()
    mysql = None
    try:
        if path.is_symlink():
            raise ValueError("配置文件是符号链接，请使用实际配置文件路径")
        raw = path.read_bytes()
        original, replacement, values, keys = migration_plan(raw.decode("utf-8"))
        if not keys:
            return {"status": "无需迁移", "changed_fields": [], "applied": False}
        cfg = connection_config(original)
        mysql = MySQLPlugin(cfg["mysql"])
        await mysql.start(None)  # Only SQL validation; never starts the plugin manager or collectors.
        store = SettingsStore(mysql, cfg["redis"].get("namespace", "empire:dev"))
        saved = await store.load("download")
        exists, existing = "global" in saved, saved.get("global")
        if exists and existing != values:
            raise RuntimeError("MySQL 已有不同的下载设置，拒绝覆盖；本地文件未修改")
        if not apply:
            return {"status": "核查通过；使用 --apply 执行", "changed_fields": keys, "applied": False}
        if path.read_bytes() != raw:
            raise RuntimeError("本地配置在核查期间变化；未写入 MySQL，请重新执行")
        if not exists:
            await store.save("download", "global", values)
        if (await store.load("download")).get("global") != values:
            raise RuntimeError("MySQL 下载设置回读不一致，保留旧配置文件")
        replace_config(path, raw, replacement)
        return {"status": "已迁入 MySQL 并移除旧配置项", "changed_fields": keys, "applied": True}
    finally:
        try:
            if mysql is not None:
                await mysql.stop()
        finally:
            lock.unlock()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--apply", action="store_true", help="提交 MySQL 后移除本地旧资源数值；默认只核查")
    args = parser.parse_args()
    cfg = {}
    try:
        cfg = connection_config(tomllib.loads(args.config.read_text(encoding="utf-8")))
        report = asyncio.run(migrate(args.config, apply=args.apply))
        print(json.dumps(report, ensure_ascii=False))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None


if __name__ == "__main__":
    main()
