"""Bounded isolated Redis benchmark of validation/dispatch, not SQL capacity.

The injected sink deliberately excludes SQL/fingerprint/history latency. Results
must not be reported as the A/B end-to-end acceptance workloads.
"""
import argparse
import asyncio
import hashlib
import json
import platform
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4


async def measure(args):
    import empire.core.config as config
    # Frozen source shares the unchanged repository resources, never its own
    # connection template. No application runtime or archive loop is started.
    config.project_root = lambda: Path(__file__).resolve().parents[1]
    from empire.contracts.data import make_envelope
    from empire.core.config import load_config
    from empire.features.builtin import dataset_contributions
    from empire.features.news.source import normalize_source
    from empire.plugins.datasets.astock import DatasetPlugin
    from empire.plugins.infra.redis_store import create_client
    from empire.plugins.pipeline.archive import ArchivePlugin

    client = create_client(load_config()['redis'])
    prefix = 'empire:test:archive-processing:' + uuid4().hex
    worker = ArchivePlugin({'work_time_ms': 5000, 'scan_time_ms': 5000})
    worker.redis = SimpleNamespace(client=client, prefix=prefix, stream=prefix + ':stream')
    worker.catalog = DatasetPlugin(dataset_contributions(
        {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}))
    worker.records = SimpleNamespace(add_archive=AsyncMock(), add_error=AsyncMock())
    counts = dict(normalize=0, processed=0, xrange=0)
    normalize, xrange = worker.catalog.normalize, client.xrange

    def count_normalize(envelope):
        counts['normalize'] += 1
        return normalize(envelope)

    async def read(*a, **kw):
        counts['xrange'] += 1
        return await xrange(*a, **kw)

    async def sink(envelope, data):
        counts['processed'] += 1
        return {'row_count': data['row_count'], 'written_count': 0}

    worker.catalog.normalize, client.xrange = count_normalize, read
    worker._archive_data = sink
    row = normalize_source({'id': 101, 'rich_text': 'benchmark-' * 10,
        'create_time': '2026-09-23 08:00:00', 'update_time': '2026-09-23 08:00:00',
        'tag': [], 'is_focus': 0})
    payload = {'page': 1, 'rows': [{**row, 'news_id': 101 - i} for i in range(50)]}
    rounds = []
    try:
        for iteration in range(args.rounds):
            counts.update(normalize=0, processed=0, xrange=0)
            async with client.pipeline(transaction=False) as pipe:
                for page in range(1, args.messages + 1):
                    event = make_envelope(source='test', dataset='news.flash.page',
                        job_key='news-test', run_id='bench', batch_id='bench',
                        business_key=str(page), payload={**payload, 'page': page})
                    pipe.xadd(worker.redis.stream, {'envelope': event.model_dump_json()})
                await pipe.execute()
            began = perf_counter()
            while await client.xlen(worker.redis.stream):
                await worker.flush()
            elapsed = perf_counter() - began
            assert counts['processed'] == args.messages
            rounds.append(dict(round=iteration, seconds=elapsed,
                messages_per_second=args.messages / elapsed, **counts))
        result = dict(kind='validation-dispatch-only', sql_measured=False,
            platform=platform.platform(), source=str(args.source), rounds=rounds,
            fixture_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + ':*')]
        if keys:
            assert all(key.startswith(prefix + ':') for key in keys)
            await client.delete(*keys)
        await client.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('src'))
    parser.add_argument('--messages', type=int, default=500)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.messages <= 10000 or not 1 <= args.rounds <= 8:
        parser.error('bounded run requires 1..10000 messages and 1..8 rounds')
    if args.output.exists():
        parser.error('output must be a new evidence file')
    sys.path.insert(0, str(args.source.resolve()))
    asyncio.run(measure(args))
