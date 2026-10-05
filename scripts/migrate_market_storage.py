"""Explicit market v1 JSON -> v2 typed storage; holds ordinary singleton and maintenance locks."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from empire.core.config import load_config
from empire.core.redaction import Redactor
from empire.plugins.infra.mysql_store import make_engine
from scripts.market_migration import maintain, preflight
from scripts.migrate_business_schema import inspect_queue


async def run(args):
    cfg = load_config(args.config)
    engine = make_engine(cfg['mysql'], read_timeout=3600)
    lock = app = None
    try:
        if args.command == 'preflight':
            result = preflight(engine)
            result['queue'] = await inspect_queue(cfg['redis'])
        else:
            from PySide6.QtCore import QCoreApplication

            from empire.__main__ import acquire_instance_lock
            app = QCoreApplication.instance() or QCoreApplication([])
            lock = acquire_instance_lock()
            if (await inspect_queue(cfg['redis']))['stream_length']:
                raise RuntimeError('待归档队列未清零，不能维护；须原归档路径成功处理')
            result = maintain(engine, args.journal, args.command)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
        print(json.dumps({'command': args.command, 'report': args.report,
                          'phase': result.get('phase'), 'passed': result.get('passed')}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(Redactor.from_config(cfg).text(exc))
        return 1
    finally:
        engine.dispose()
        if lock:
            lock.unlock()
        del app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight', 'migrate', 'verify', 'status', 'resume', 'rollback'])
    parser.add_argument('--config')
    parser.add_argument('--journal', default='build/kaipanla-optimization/migration.json')
    parser.add_argument('--report', default='build/kaipanla-optimization/maintenance-report.json')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
