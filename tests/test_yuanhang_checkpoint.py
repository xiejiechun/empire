"""Pool-size checkpoint regression and partial-publication recovery."""
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang import collector as module
from empire.plugins.infra.routing import USE_PROXY


class MemoryIngest:
    def __init__(self):
        self.redis = SimpleNamespace(prefix='test')
        self.state = dict(revision=0, cursor={})
        self.sizes, self.messages = [], []
        self.fail_page = None

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def advance_checkpoint(self, *, expected_revision, cursor, **kwargs):
        assert expected_revision == self.state['revision']
        size = len(json.dumps(cursor, ensure_ascii=False, allow_nan=False).encode())
        assert size <= 16384, 'Checkpoint is too large'
        assert 'work_codes' not in cursor and 'plans' not in cursor
        self.sizes.append(size)
        self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
        return copy.deepcopy(self.state)


@asynccontextmanager
async def sequential_reads(c, units, fetch, **kwargs):
    async def read():
        for i, unit in enumerate(units):
            yield i, SimpleNamespace(resolve=lambda unit=unit: fetch(unit))
    yield read()


def harness(monkeypatch, codes, *, financial=False, mode='full'):
    c = module.YuanhangCollector(financial=financial)
    c.ingest = MemoryIngest()
    async def plans(namespace, selected, through, force=False, scope='all'):
        return {code: dict(code=code, mode='skip' if scope == 'backfill' else 'full' if force else mode, start='1900-01-01',
                           end=through, native_market='USZA', reason='fixture') for code in selected}
    c.query = SimpleNamespace(collection_scope=AsyncMock(return_value=(codes, '2026-10-23')),
        daily_plans=AsyncMock(side_effect=plans), financial_markets=AsyncMock(return_value={}),
        has_history=AsyncMock(return_value=False))
    c.identity = SimpleNamespace(registry=SimpleNamespace(load=AsyncMock(return_value={
        'node': SimpleNamespace(provisioned=True)})), online_codes=lambda: {'node'})
    c.records = SimpleNamespace(sanitize_text=str)
    c.fetch = AsyncMock(return_value=SimpleNamespace(observed_at=datetime.now(timezone.utc)))
    c.confirmation = SimpleNamespace(page_status=AsyncMock())
    async def publish(ingest, stats, messages, **kwargs):
        if ingest.fail_page == kwargs['cursor']['pages']:
            raise ValueError('fixture interrupted publication')
        state = await ingest.advance_checkpoint(**kwargs)
        ingest.messages.extend(messages)
        return state
    monkeypatch.setattr(module, 'publish_with_capacity', publish)
    monkeypatch.setattr(module, 'prefetch_units', sequential_reads)
    monkeypatch.setattr(module, 'record_error_safely', AsyncMock())
    monkeypatch.setattr(module, 'daily_years', lambda snap, code, through: [
        dict(code=code, year=2025, rows=[]), dict(code=code, year=2026, rows=[])])
    monkeypatch.setattr(module, 'daily_ranges', lambda snap, code, start, through: [
        dict(code=code, year=2025, rows=[]), dict(code=code, year=2026, rows=[])])
    monkeypatch.setattr(module, 'financial_payload', lambda snap, code: dict(code=code, actions=[], capital=[]))
    async def wait(*args, **kwargs):
        assert c.ingest.state['cursor']['next_index'] == len(codes)
        assert c.ingest.state['cursor']['phase'] == 'awaiting_archive'
    monkeypatch.setattr(module, 'wait_for_archive', AsyncMock(side_effect=wait))
    return c


@pytest.mark.parametrize('financial', [False, True])
async def test_maximum_15000_stock_pool_does_not_serialize_pool_or_plans(monkeypatch, financial):
    codes = [f'{i:06}.SZ' for i in range(15000)]
    c = harness(monkeypatch, codes, financial=financial)
    token = USE_PROXY.set(True)
    try:
        result = await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert result['phase'] == 'complete' and result['next_index'] == 15000
    assert c.fetch.await_count == 15000
    assert result['pages'] == len(c.ingest.messages) == 15000 * (1 if financial else 2)
    assert max(c.ingest.sizes) < 1200
    assert module.wait_for_archive.await_count == 1


async def test_partial_year_resume_pins_plan_while_sql_changes_and_cutoff_advances(monkeypatch):
    codes = ['000001.SZ', '000002.SZ', '000003.SZ']
    c = harness(monkeypatch, codes)
    c.ingest.fail_page = 2
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(ValueError, match='interrupted'):
            await c.execute(fresh=True)
        old = copy.deepcopy(c.ingest.state)
        assert old['cursor']['next_index'] == 0 and old['cursor']['next_year'] == 2026
        pinned = old['cursor']['current_plan']
        assert pinned['mode'] == 'full'
        # A partial SQL archive must not shorten the current security to skip/range.
        c.query.collection_scope.return_value = (codes, '2026-10-26')
        async def replanned(ns, selected, through, force=False, scope='all'):
            assert codes[0] not in selected and through == '2026-10-23' and force
            return {code: {**pinned, 'code': code} for code in selected}
        c.query.daily_plans.side_effect = replanned
        c.ingest.fail_page = None
        result = await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert result['pages'] == len(c.ingest.messages) == 6
    assert result['through'] == '2026-10-23' and result['phase'] == 'complete'
    assert [e.raw_payload['history']['year'] for e in c.ingest.messages] == [2025,2026,2025,2026,2025,2026]
    assert 'current_plan' not in c.ingest.state['cursor']


async def test_sparse_skip_positions_and_trailing_skips_resume_in_complete_pool(monkeypatch):
    codes = [f'{i:06}.SZ' for i in range(8)]
    c = harness(monkeypatch, codes, mode='skip')
    async def plans(ns, selected, through, force=False, scope='all'):
        return {code: dict(mode='full' if scope != 'backfill' and code in (codes[2], codes[5]) else 'skip') for code in selected}
    c.query.daily_plans.side_effect = plans
    c.ingest.fail_page = 3
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(ValueError, match='interrupted'):
            await c.execute()
        assert c.ingest.state['cursor']['next_index'] == 3
        assert c.ingest.state['cursor']['skipped_units'] == 2
        c.ingest.fail_page = None
        result = await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert result['pages'] == 4 and result['skipped_units'] == 6
    assert c.query.daily_plans.await_args_list[-2].args[1] == codes[3:]
    assert [e.raw_payload['history']['code'] for e in c.ingest.messages] == [codes[2]]*2 + [codes[5]]*2


async def test_all_skipped_needs_no_source_or_identity_request(monkeypatch):
    c = harness(monkeypatch, ['000001.SZ'], mode='skip')
    token = USE_PROXY.set(True)
    try:
        result = await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert result['pages'] == 0 and result['skipped_units'] == 1
    c.fetch.assert_not_awaited()
    c.identity.registry.load.assert_not_awaited()


async def test_backfill_is_bounded_and_resume_does_not_extend_the_batch(monkeypatch):
    codes = [f'{i:06}.SZ' for i in range(100)]
    c = harness(monkeypatch, codes)
    async def plans(ns, selected, through, force=False, scope='all'):
        return {code: dict(mode='skip' if scope == 'recent' else 'full') for code in selected}
    c.query.daily_plans.side_effect = plans
    c.ingest.fail_page = 21
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(ValueError, match='interrupted'):
            await c.execute()
        assert c.ingest.state['cursor']['round_end'] == 64
        c.ingest.fail_page = None
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
    finally:
        USE_PROXY.reset(token)
    assert result['pages'] == 128
    assert len({e.raw_payload['history']['code'] for e in c.ingest.messages}) == 64
    assert c.stats['total_units'] == 54


@pytest.mark.parametrize('financial', [False, True])
async def test_previous_day_archive_resume_updates_today_in_same_daily_invocation(monkeypatch, financial):
    codes = ['000001.SZ']
    c = harness(monkeypatch, codes, mode='range', financial=financial)
    c.ingest.state['cursor'] = dict(contract=2, phase='awaiting_archive',
        maintenance_scope='backfill', scope_hash=module.digest(codes), through='2026-10-22',
        next_index=1, next_year=1900, snapshot_hash='', pages=1, collected=0,
        batch_id='yesterday', run_date='2026-10-22', force_full=False, skipped_units=0, deferred={})
    token = USE_PROXY.set(True)
    try:
        result = await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert result['through'] == '2026-10-23'
    assert c.fetch.await_count == 1 and c.fetch.call_args.args[0][2] == '2026-10-23'
    assert module.wait_for_archive.await_count == 2
    assert all(e.batch_id != 'yesterday' for e in c.ingest.messages)


async def test_old_pool_plan_cursor_requires_explicit_maintenance(monkeypatch):
    c = harness(monkeypatch, ['000001.SZ'])
    c.ingest.state['cursor'] = dict(phase='collecting', scope_hash=module.digest(['000001.SZ']),
                                   work_codes=['000001.SZ'], plans={})
    old = copy.deepcopy(c.ingest.state)
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(ValueError, match='显式维护'):
            await c.execute()
    finally:
        USE_PROXY.reset(token)
    assert c.ingest.state == old


@pytest.mark.parametrize('index,phase', [(0, 'collecting'), (1, 'collecting'), (2, 'complete')])
def test_explicit_conversion_maps_filtered_position_and_preserves_batch(index, phase):
    from scripts.migrate_yuanhang_checkpoint import upgrade
    codes = [f'{i:06}.SZ' for i in range(6)]
    work = [codes[1], codes[4]]
    cursor = dict(phase=phase, scope_hash=module.digest(codes), next_index=index,
                  next_year=1900, snapshot_hash='', pages=index, batch_id='same-batch',
                  work_codes=work, plans={code: dict(mode='full') for code in work})
    before = copy.deepcopy(cursor)
    converted = upgrade(cursor, codes)
    position = [1, 4, 6][index]
    assert converted['next_index'] == position and converted['skipped_units'] == position-index
    assert converted['batch_id'] == 'same-batch' and cursor == before
    assert upgrade(converted, codes) == converted


def test_conversion_pins_partial_security_and_refuses_changed_scope():
    from scripts.migrate_yuanhang_checkpoint import upgrade
    codes = ['000001.SZ', '000002.SZ']
    plan = dict(mode='full', reason='explicit_full_verification')
    cursor = dict(phase='collecting', scope_hash=module.digest(codes), next_index=0,
                  next_year=2021, snapshot_hash='hash', work_codes=[codes[1]], plans={codes[1]:plan})
    converted = upgrade(cursor, codes)
    assert converted['current_plan'] == plan and converted['force_full']
    assert converted['next_year'] == 2021 and converted['next_index'] == 1
    with pytest.raises(ValueError, match='scope differs'):
        upgrade(cursor, codes[:1])
