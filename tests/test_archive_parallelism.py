"""Ownership spans normalized validation, transaction, history, progress and ACK."""
import asyncio
import threading
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empire.contracts.data import make_envelope
from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.pipeline.archive import ArchivePlugin
from tests.catalog_factory import builtin_catalog


async def test_independent_tables_overlap_shared_tables_and_project_state_serialize():
    worker = ArchivePlugin({'work_max_units': 8, 'work_time_ms': 5000})
    worker.catalog = builtin_catalog()
    worker._scan = AsyncMock()
    worker._history = AsyncMock()
    worker._incremental_result = AsyncMock()
    worker.redis = SimpleNamespace(stream='test:stream', client=SimpleNamespace(xlen=AsyncMock(return_value=0)))
    events = {}
    for i, (project, dataset) in enumerate([
            ('news-a', 'news.flash.page'), ('news-b', 'news.flash.page'),
            ('calendar', 'calendar.month'), ('calendar', 'calendar.month')]):
        event = make_envelope(source='test', dataset=dataset, job_key=project,
            run_id='run', batch_id=str(i), business_key=str(i), payload={})
        ident = f'1-{i}'
        events[ident] = event
        worker.queue.add(ident, event, True, project,
                         domains=worker.catalog.archive_domains(event))
    active, order, peak = Counter(), [], 0

    async def load(ids, computation, project):
        return [{'id': ident, 'envelope': events[ident],
                 'normalized': {'page': int(ident.split('-')[1]), 'row_count': 1}} for ident in ids]

    async def write(event, data):
        nonlocal peak
        domain = 'news' if event.dataset.startswith('news') else 'calendar'
        active[domain] += 1
        assert active[domain] == 1
        peak = max(peak, sum(active.values()))
        await asyncio.sleep(.01)
        order.append((event.job_key, data['page']))
        active[domain] -= 1
        return {'row_count': 1}

    async def acknowledge(ids):
        worker.queue.forget(ids)

    worker._load_records, worker._archive_data, worker.acknowledge = load, write, acknowledge
    await worker.flush()
    assert peak == 2 and len(order) == 4
    assert [page for project, page in order if project == 'calendar'] == [2, 3]
    assert not worker.queue.ids


async def test_unknown_dataset_ownership_is_exclusive():
    worker = ArchivePlugin({})
    event = SimpleNamespace(source='test', job_key='p', batch_id='a', dataset='custom')
    worker.queue.add('1-0', event, True, 'p')
    assert worker.queue.take(occupied={('table', 'finance_news')}) is None
    assert worker.queue.take().domains == frozenset({'*'})


def test_registered_table_names_without_an_explicit_write_audit_stay_exclusive():
    from empire.plugins.datasets.astock import DatasetPlugin

    catalog = builtin_catalog()
    event = make_envelope(source='sina', dataset='news.flash.page', job_key='sina-news-v1',
                          run_id='r', batch_id='b', business_key='p', payload={})
    contribution = catalog.mapping(event)
    assert ('table', 'finance_news') in catalog.archive_domains(event)
    for tables in ((), ('stock',)):
        unreviewed = DatasetPlugin([replace(contribution, archive_tables=tables)])
        assert unreviewed.archive_domains(event) == frozenset({'*'})


async def test_isolated_project_is_preserved_but_not_reported_as_shared_ready_pressure():
    worker = ArchivePlugin({})
    worker.catalog = builtin_catalog()
    worker._scan = AsyncMock()
    worker._recheck_isolated = AsyncMock()
    worker.redis = SimpleNamespace(stream='test:stream', client=SimpleNamespace(xlen=AsyncMock(return_value=1)))
    event = make_envelope(source='sina', dataset='news.flash.page', job_key='blocked',
                          run_id='r', batch_id='b', business_key='p', payload={})
    worker.queue.add('1-0', event, True, 'blocked')
    worker.isolated['1-1'] = 'blocked'
    worker._process_batch = AsyncMock()
    await worker.flush()
    worker._process_batch.assert_not_awaited()
    assert '1-0' in worker.queue.ids and worker.isolated == {'1-1': 'blocked'}
    assert worker.stats['ready_pending'] == worker.stats['ready_projects'] == 0
    assert worker.stats['ready_oldest_ms'] is None


async def test_byte_target_keeps_every_prepared_result_and_splits_only_at_sql_boundary():
    worker = ArchivePlugin({})
    events = [make_envelope(source='sina', dataset='news.flash.page', job_key='p',
              run_id='r', batch_id='b', business_key=str(i), payload={}) for i in range(16)]
    wires = [event.model_dump_json() for event in events]

    @asynccontextmanager
    async def computed(inputs, operation, *, serialized):
        assert len(inputs) == 16 and serialized == wires and operation == 'normalize'
        yield [(dict(normalized={'page': i, 'row_count': 1, 'rows': []},
                     normalized_bytes=2 * 1024 * 1024, namespace='news',
                     plan={str(i): (None, [])}, hashes={}), None) for i in range(16)]

    worker.catalog = SimpleNamespace(computed=computed, archive_envelope=type(events[0]).model_validate_json,
        incremental=lambda event: True, project_id=lambda event: 'p',
        fingerprint_source=lambda event: 'sina', mapping=lambda event: SimpleNamespace(batch_independent=True))
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock()
    pipe.execute = AsyncMock(return_value=[[(str(i), {'envelope': raw})] for i, raw in enumerate(wires)])
    worker.redis = SimpleNamespace(stream='test', client=SimpleNamespace(pipeline=lambda **kw: pipe))
    async with AsyncExitStack() as computation:
        records = await worker._load_records([str(i) for i in range(16)], computation, 'p')
    assert [record['id'] for record in records] == [str(i) for i in range(16)]
    worker._flush_units = AsyncMock()
    await worker._flush_incremental(records, 'p')
    groups = [call.args[0] for call in worker._flush_units.await_args_list]
    assert [len(group) for group in groups] == [2] * 8
    assert [record['id'] for group in groups for record in group] == [str(i) for i in range(16)]


async def test_slow_archive_cannot_block_control_saves_and_shutdown_retains_workers(monkeypatch):
    monkeypatch.setattr('empire.plugins.infra.mysql_store.make_engine', lambda *a, **kw: MagicMock())
    monkeypatch.setattr(MySQLPlugin, '_validate', lambda self: 'test')
    mysql = MySQLPlugin({'database': 'test'})
    await mysql.start(None)
    entered, release = threading.Event(), threading.Event()

    def writer(conn, envelope, normalized):
        entered.set()
        assert release.wait(5)
        return 'committed'

    task = asyncio.create_task(mysql.archive([{'writer': writer, 'envelope': None, 'normalized': {}}]))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(.001)
        assert await asyncio.wait_for(mysql.control(lambda: 'saved'), 1) == 'saved'
        assert mysql.archive_lane.active == 1 and mysql.control_lane.active == 0
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and mysql.archive_lane.active == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert mysql.archive_lane.active == 0
        assert mysql.archive_engine.begin.called
        assert not mysql.engine.begin.called
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await mysql.stop()
