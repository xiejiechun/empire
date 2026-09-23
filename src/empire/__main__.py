from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from empire.core.config import RedactingFormatter, load_config, redact, user_data_dir


def configure_logging(cfg: dict) -> None:
    handler = RotatingFileHandler(
        user_data_dir() / "empire.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(RedactingFormatter(cfg))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def acquire_instance_lock():
    from PySide6.QtCore import QLockFile

    lock = QLockFile(str(user_data_dir() / "empire.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise RuntimeError("Empire 已在当前用户下运行，请先关闭其他窗口或写入任务。")
    return lock


async def doctor(cfg: dict) -> dict:
    import redis.asyncio as redis
    from sqlalchemy import URL, create_engine, text

    result = {}
    settings = cfg["redis"]
    client = redis.Redis(
        host=settings.get("host", "127.0.0.1"), port=settings.get("port", 6379),
        password=settings.get("password") or None, db=settings.get("db", 0),
        decode_responses=True, socket_connect_timeout=5, socket_timeout=5,
    )
    try:
        server = await client.info("server")
        memory = await client.info("memory")
        persistence = await client.info("persistence")
        capabilities = await client.execute_command(
            "COMMAND", "INFO", "XADD", "XREADGROUP", "XAUTOCLAIM", "EVAL", "TIME"
        )
        result["redis"] = {
            "connected": True, "version": server.get("redis_version"),
            "aof_enabled": persistence.get("aof_enabled"),
            "maxmemory_policy": memory.get("maxmemory_policy"),
            "used_memory": memory.get("used_memory"), "maxmemory": memory.get("maxmemory"),
            "required_commands": bool(capabilities and all(capabilities.values())),
            "namespace": settings.get("namespace", "empire:dev"),
        }
    except Exception as exc:
        result["redis"] = {"connected": False, "error": redact(exc, cfg)}
    finally:
        await client.aclose()

    def mysql_check():
        settings = cfg["mysql"]
        engine = create_engine(URL.create(
            "mysql+pymysql", username=settings["user"], password=settings.get("password"),
            host=settings.get("host", "127.0.0.1"), port=settings.get("port", 3306),
            database=settings["database"], query={"charset": "utf8mb4"},
        ), connect_args={"connect_timeout": 5, "read_timeout": 10, "write_timeout": 10})
        try:
            with engine.connect() as connection:
                version = connection.execute(text("SELECT VERSION()" )).scalar_one()
                tables = connection.execute(text("SHOW TABLES")).scalars().all()
                return {"connected": True, "version": version, "database": settings["database"],
                        "port": settings.get("port", 3306), "tables": tables}
        except Exception as exc:
            return {"connected": False, "error": redact(exc, cfg)}
        finally:
            engine.dispose()

    result["mysql"] = await asyncio.to_thread(mysql_check)
    return result


def run_gui(cfg: dict, screenshot: str | None = None, smoke_seconds: int = 0) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from empire.bootstrap import build_manager
    from empire.core.runtime import Runtime
    from empire.desktop.window import MainWindow

    app = QApplication(sys.argv[:1])
    if not QFontDatabase.families():
        # Qt's offscreen platform does not discover Windows fonts automatically.
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font = Path("C:/Windows/Fonts") / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
    app.setApplicationName("Empire")
    app.setOrganizationName("EmpireResearch")
    lock = acquire_instance_lock()
    runtime = Runtime(lambda: build_manager(cfg), cfg)
    runtime.start()
    window = MainWindow(runtime, cfg)
    window.show()
    if smoke_seconds:
        def finish():
            if screenshot:
                target = Path(screenshot).resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(target))
            window.close()
        QTimer.singleShot(smoke_seconds * 1000, finish)
    try:
        return app.exec()
    finally:
        if not runtime.closed.is_set():
            runtime.command("shutdown").result(timeout=60)
        runtime.thread.join(timeout=60)
        lock.unlock()


def main() -> int:
    parser = argparse.ArgumentParser(description="Empire 投资研究桌面")
    parser.add_argument("--config", help="本地 TOML 配置路径")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", help="启动桌面（默认）")
    commands.add_parser("doctor", help="只读检查数据库连接与必要能力")
    commands.add_parser("init-db", help="在已配置的数据库中显式创建首次使用的表")
    collect = commands.add_parser("collect-stocks", help="采集完整股票列表、归档并退出")
    collect.add_argument("--fresh", action="store_true", help="创建新批次，放弃续跑旧断点")
    news = commands.add_parser("collect-news", help="采集新浪财经新闻、等待归档并退出")
    news.add_argument("--fresh", action="store_true", help="从最新窗口重新建立基线，保留已归档新闻")
    calendar = commands.add_parser("collect-calendar", help="补齐巨潮交易日历并维护本月至下一年年底")
    calendar.add_argument("--fresh", action="store_true", help="重新核验全部历史和未来范围，保留已归档日期")
    smoke = commands.add_parser("smoke", help="启动桌面并在指定秒数后安全退出")
    smoke.add_argument("--seconds", type=int, default=8)
    smoke.add_argument("--screenshot")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        configure_logging(cfg)
        if args.command == "doctor":
            result = asyncio.run(doctor(cfg))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if all(value.get("connected") for value in result.values()) else 1
        if args.command == "init-db":
            from empire.plugins.infra.mysql_store import initialize_database
            lock = acquire_instance_lock()
            try:
                initialize_database(cfg["mysql"])
                print("初始化完成。仅创建缺失表，未执行历史数据迁移。")
            finally:
                lock.unlock()
            return 0
        if args.command in ("collect-stocks", "collect-news", "collect-calendar"):
            from empire.bootstrap import build_manager
            lock = acquire_instance_lock()

            async def collect_once():
                manager = build_manager(cfg)
                task_id = {"collect-news": "sina-news", "collect-stocks": "sina-stocks",
                           "collect-calendar": "cninfo-calendar"}[args.command]
                try:
                    await manager.start("collection.control")
                    await manager.start("pipeline.archive")
                    control = manager.registry.get("collection.control")
                    run_id = await control.run(task_id, fresh=args.fresh)
                    waiter = control.tasks[task_id]
                    while not waiter.done():
                        done, _ = await asyncio.wait({waiter}, timeout=10)
                        if not done:
                            definition = control.definitions[task_id]
                            print(json.dumps(manager.registry.get(definition.capability).health(),
                                             ensure_ascii=False), flush=True)
                    await waiter
                    record = next(row for row in control.state["history"] if row["run_id"] == run_id)
                    if record["status"] != "complete":
                        raise RuntimeError(record["error"] or record["status"])
                    result = record["result"]
                    print(json.dumps({**result, "status": "complete"}, ensure_ascii=False), flush=True)
                finally:
                    await manager.shutdown()
            try:
                asyncio.run(collect_once())
            finally:
                lock.unlock()
            return 0
        if args.command == "smoke":
            return run_gui(cfg, args.screenshot, args.seconds)
        return run_gui(cfg)
    except Exception as exc:
        print(redact(exc, locals().get("cfg", {})), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
