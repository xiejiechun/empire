"""Paired pure normalization/hash experiment including full process result IPC.

No Redis, SQL, public website, or running application is touched. Returning the
full normalized unit is required; a tiny checksum-only return hides IPC cost.
"""
import argparse
import asyncio
import hashlib
import json
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter, process_time


def compute(raw):
    from empire.contracts.data import Envelope
    from empire.plugins.pipeline.fingerprints import digest
    from tests.catalog_factory import builtin_catalog
    global _catalog
    if '_catalog' not in globals():
        _catalog = builtin_catalog()
    envelope = Envelope.model_validate_json(raw)
    data = _catalog.normalize(envelope)
    namespace, plan = _catalog.fingerprint_plan(envelope, data)
    hashes = {ident: dict(hash=digest(content), version=version)
              for ident, (content, version) in plan.items()}
    return data, namespace, hashes


async def measure(args):
    from archive_capacity_fixtures import fixture

    from empire.contracts.data import make_envelope
    from empire.plugins.pipeline.fingerprints import digest
    values = [make_envelope(**fixture(args.dataset, i % 32, large=args.large),
                run_id='compute', batch_id='compute').model_dump_json() for i in range(args.messages)]
    pools = {workers: ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context('spawn'))
             for workers in (2, 4)}
    result, checks = [], []
    try:
        # Warm every worker and the direct code path outside the timed trials.
        expected = compute(values[0])
        expected_digest = digest(expected)
        loop = asyncio.get_running_loop()
        for workers, pool in pools.items():
            samples = await asyncio.gather(*(loop.run_in_executor(pool, compute, values[0]) for _ in range(workers * 2)))
            assert all(digest(sample) == expected_digest for sample in samples)
        for trial, order in enumerate(((0, 2, 4), (4, 2, 0), (0, 2, 4), (4, 2, 0))):
            for workers in order:
                started, cpu = perf_counter(), process_time()
                verified = 0
                for offset in range(0, len(values), 16):
                    batch = values[offset:offset + 16]
                    if workers:
                        data = await asyncio.gather(*(loop.run_in_executor(pools[workers], compute, raw) for raw in batch))
                    else:
                        data = [compute(raw) for raw in batch]
                    verified += sum(item[0]['row_count'] for item in data)
                    del data
                seconds, cpu_seconds = perf_counter() - started, process_time() - cpu
                result.append(dict(trial=trial, workers=workers, seconds=seconds,
                    messages_per_second=len(values) / seconds, parent_cpu_seconds=cpu_seconds,
                    business_rows=verified))
                checks.append(verified)
        assert len(set(checks)) == 1
    finally:
        for pool in pools.values():
            pool.shutdown(wait=True, cancel_futures=True)
    report = dict(kind='pure-compute-full-result-IPC', dataset=args.dataset, large=args.large,
        messages=args.messages, trials=result,
        fixture_sha256=hashlib.sha256(''.join(values).encode()).hexdigest(),
        result_bytes=len(json.dumps(expected, ensure_ascii=False).encode()),
        business_verified=True, end_to_end_acceptance=False)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=('financial', 'capital', 'calendar'), default='financial')
    parser.add_argument('--large', action='store_true')
    parser.add_argument('--messages', type=int, default=256)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 16 <= args.messages <= 1024:
        parser.error('new output and 16..1024 messages required')
    sys.path[:0] = [str(Path('src').resolve()), str(Path('.').resolve())]
    asyncio.run(measure(args))
