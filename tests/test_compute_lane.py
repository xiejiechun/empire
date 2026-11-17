"""Real spawned workers, retained cancellation ownership and shared-byte limits."""
import asyncio
import json
import os
import pickle
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from empire.computation import execute
from empire.contracts.data import BackpressureError, Envelope, make_envelope, read_envelope_metadata
from empire.plugins.infra.compute_lane import ComputeLane
from empire.plugins.infra.resources import ByteBudget
from empire.plugins.pipeline.fingerprints import digest
from scripts.archive_capacity_fixtures import fixture
from tests.catalog_factory import builtin_catalog


def held_compute(started, gate):
    Path(started).write_text('started')
    until = time.monotonic() + 10
    while not Path(gate).exists() and time.monotonic() < until:
        time.sleep(.01)
    return 'finished'


def crash_compute():
    os._exit(7)


@pytest.mark.parametrize('damage', ['body-list', 'body-null', 'body-string', 'extra',
                                    'missing-body', 'timezone', 'schema', 'identity'])
def test_metadata_projection_preserves_envelope_rejections(damage):
    value = json.loads(make_envelope(**fixture('financial', 0), run_id='t', batch_id='t').model_dump_json())
    if damage.startswith('body-'):
        value['raw_payload'] = {'body-list': [], 'body-null': None, 'body-string': '{}'}[damage]
    elif damage == 'extra':
        value['future-field'] = 1
    elif damage == 'missing-body':
        del value['raw_payload']
    elif damage == 'timezone':
        value['observed_at'] = '2026-11-06T12:00:00'
    elif damage == 'schema':
        value['schema_version'] = 0
    else:
        value['event_id'] = 'short'
    raw = json.dumps(value)
    for reader in (Envelope.model_validate_json, read_envelope_metadata):
        with pytest.raises(ValueError):
            reader(raw)


def test_metadata_projection_keeps_every_header_field_and_never_materializes_payload():
    event = make_envelope(**fixture('financial', 0), run_id='t', batch_id='t')
    header = read_envelope_metadata(event.model_dump_json())
    assert type(header) is Envelope
    assert header == event.model_copy(update={'raw_payload': {}})


async def test_process_uses_formal_normalization_hashes_and_keeps_bytes_until_consumed():
    catalog = builtin_catalog()
    catalog.compute_operation = execute
    budget = ByteBudget(256 * 1024 * 1024)
    context = SimpleNamespace(get=lambda name: SimpleNamespace(buffer_budget=budget))
    await catalog.start(context)
    values = [make_envelope(**fixture('financial', i), run_id='test', batch_id='test') for i in range(4)]
    try:
        async with catalog.computed(values, 'canonicalize') as canonical:
            assert budget.used > 0
            from empire.contracts.data import Envelope
            assert [Envelope.model_validate_json(value['publication']) for value, error in canonical
                    if error is None] == [catalog.canonicalize(e) for e in values]
            assert all(value['envelope'].raw_payload == {} for value, _ in canonical)
        assert budget.used == 0
        async with catalog.computed(values, 'normalize') as prepared:
            assert budget.used > 0
            for event, (result, error) in zip(values, prepared):
                assert error is None
                expected = catalog.normalize(event)
                assert {**result['normalized'], 'rows': pickle.loads(result['rows_pickle'])} == expected
                namespace, plan = catalog.fingerprint_plan(event, expected)
                assert result['namespace'] == namespace
                assert result['hashes'] == {key: dict(hash=digest(content), version=version)
                                           for key, (content, version) in plan.items()}
        assert budget.used == 0
        assert catalog.compute_lane.health()['started']
        assert catalog.compute_lane.pending == 0
    finally:
        await catalog.stop()


async def test_budget_failure_does_not_wait_on_owned_input_or_submit_process():
    catalog = builtin_catalog()
    catalog.compute_operation = execute
    budget = ByteBudget(32 * 1024 * 1024)
    await catalog.start(SimpleNamespace(get=lambda name: SimpleNamespace(buffer_budget=budget)))
    held = budget.try_reserve(budget.limit)
    event = make_envelope(**fixture('financial', 0), run_id='test', batch_id='test')
    try:
        with pytest.raises(BackpressureError, match='共享缓冲'):
            async with catalog.computed([event], 'normalize'):
                pytest.fail('must reject before work')
        assert not catalog.compute_lane.health()['started']
        assert budget.used == held.size
    finally:
        held.release()
        await catalog.stop()
    assert budget.used == 0


async def test_existing_stream_wire_retains_content_validation_and_checks_header_identity():
    catalog = builtin_catalog()
    catalog.compute_operation = execute
    budget = ByteBudget(64 * 1024 * 1024)
    await catalog.start(SimpleNamespace(get=lambda name: SimpleNamespace(buffer_budget=budget)))
    event = make_envelope(**fixture('financial', 0), run_id='test', batch_id='test')
    try:
        async with catalog.computed([event], 'normalize', serialized=[event.model_dump_json()]) as prepared:
            value, error = prepared[0]
            assert error is None
            assert pickle.loads(value['rows_pickle']) == catalog.normalize(event)['rows']
        other = event.model_copy(update={'batch_id': 'other'})
        with pytest.raises(ValueError, match='身份'):
            async with catalog.computed([event], 'normalize', serialized=[other.model_dump_json()]):
                pytest.fail('wrong original wire must not confirm this message')
        damaged = event.model_copy(update={'raw_payload': {**event.raw_payload, 'page': 999}})
        async with catalog.computed([event], 'normalize', serialized=[damaged.model_dump_json()]) as prepared:
            assert isinstance(prepared[0][1], ValueError)
            assert 'hash mismatch' in str(prepared[0][1])
        assert budget.used == 0 and catalog.compute_lane.pending == 0
    finally:
        await catalog.stop()


async def test_small_saved_budget_reduces_compute_wave_without_rejecting_legal_page():
    catalog = builtin_catalog()
    catalog.compute_operation = execute
    budget = ByteBudget(12 * 1024 * 1024)
    await catalog.start(SimpleNamespace(get=lambda name: SimpleNamespace(buffer_budget=budget)))
    values = [make_envelope(**fixture('financial', i), run_id='test', batch_id='test') for i in range(4)]
    try:
        async with catalog.computed(values, 'normalize') as prepared:
            assert all(error is None for _, error in prepared)
            assert [result['normalized']['unit'] for result, _ in prepared] == [e.business_key for e in values]
            assert 0 < budget.used <= budget.peak <= budget.limit
        assert budget.used == 0
    finally:
        await catalog.stop()


async def test_repeated_cancel_holds_process_ownership_and_close_waits(tmp_path):
    lane = ComputeLane(1)
    started, gate = tmp_path / 'started', tmp_path / 'gate'
    task = asyncio.create_task(lane.call(held_compute, str(started), str(gate)))
    async with asyncio.timeout(15):
        while not started.exists():
            await asyncio.sleep(.01)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    closing = asyncio.create_task(lane.close())
    await asyncio.sleep(.03)
    assert lane.active == lane.pending == 1
    assert not task.done() and not closing.done()
    gate.write_text('finish')
    with pytest.raises(asyncio.CancelledError):
        await task
    await closing
    assert lane.active == lane.pending == 0
    assert lane.executor is None


async def test_crashed_child_fails_closed_without_resubmitting_work():
    from concurrent.futures.process import BrokenProcessPool

    lane = ComputeLane(1)
    try:
        with pytest.raises(BrokenProcessPool):
            await lane.call(crash_compute)
        assert lane.active == lane.pending == 0
        with pytest.raises(BrokenProcessPool):
            await lane.call(sum, [1, 2])
        assert lane.active == lane.pending == 0
    finally:
        await lane.close()
