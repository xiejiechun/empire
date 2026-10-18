"""Explicit read-only inventory and official preparation checks; starts no collector."""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from empire.bootstrap import build_manager  # noqa: E402
from empire.core.config import load_config  # noqa: E402
from empire.core.time import CHINA  # noqa: E402


def encode(value):
    return asdict(value) if is_dataclass(value) else str(value)


async def scan(args):
    manager = build_manager(load_config(args.config))
    result = dict(started_at=datetime.now(CHINA).isoformat(), read_only=True, unavailable=[])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=encode) + '\n', encoding='utf-8')
    try:
        await manager.start('infra.mysql')
        # Redis is optional read evidence. Do not start control, ingest or archive services.
        try:
            await manager.start('infra.redis')
        except Exception:
            result['unavailable'].append('infra.redis')
        if args.detailed:
            for ident in manager.entries:
                if ident.startswith('data.') and ident != 'data.preparation':
                    try:
                        await manager.start(ident)
                    except Exception:
                        result['unavailable'].append(ident)
        await manager.start('data.preparation')
        query = manager.registry.get('preparation.query')
        result['inventory'] = await query.inventory(True)
        save()
        print('SQL inventory finished', flush=True)
        if args.detailed:
            # Call the sole report checker without writing its optional Redis report cache.
            from empire.contracts.preparation_scope import PreparationScope
            request = dict(purpose='analysis', study='value', focus='operating', scan='all')
            task = asyncio.create_task(query._run_report(request, PreparationScope.parse(request)))
            previous = -1
            while not task.done():
                await asyncio.wait({task}, timeout=10)
                progress = await query.snapshot(request)
                if progress and progress['checked_requirements'] != previous:
                    previous = progress['checked_requirements']
                    result['report'] = progress
                    save()
                    print(f"Checks: {previous}/{progress['total_requirements']} {progress['current_requirement']}", flush=True)
            result['report'] = await task
        result['finished_at'] = datetime.now(CHINA).isoformat()
        save()
    finally:
        await manager.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--output', required=True)
    parser.add_argument('--detailed', action='store_true')
    asyncio.run(scan(parser.parse_args()))
