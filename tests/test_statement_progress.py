from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.financial_statements.collector import ThsStatementCollector
from empire.features.financial_statements.contract import digest


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['income', 'balance', 'cashflow'])
@pytest.mark.parametrize('resume', [0, 1, 2])
async def test_stock_progress_initial_resume_and_archive(monkeypatch, kind, resume):
    stocks = [dict(market='SZ', code='000001'), dict(market='SZ', code='000002')]
    cursor = dict(phase='awaiting_archive' if resume == 2 else 'fetch', batch_id='batch',
                  index=resume, pages=resume, collected=0, units=2,
                  scope_hash=digest(['SZ:000001', 'SZ:000002']), rolling=digest([]))
    c = ThsStatementCollector(kind)
    c.query = SimpleNamespace(securities=AsyncMock(return_value=stocks))
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision': 1, 'cursor': cursor}),
                              advance_checkpoint=AsyncMock())
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock())
    snapshots = []

    @asynccontextmanager
    async def prefetch(owner, selected, download, **kwargs):
        snapshots.append(deepcopy(owner.health()))
        async def results():
            for number, _ in enumerate(selected):
                yield number, SimpleNamespace(resolve=AsyncMock(return_value=([], None, None)))
        yield results()

    async def publish(state, following, *args):
        # Progress must still reflect the previous successful publish here.
        snapshots.append(deepcopy(c.health()))
        return {'revision': state['revision'] + 1, 'cursor': following}

    async def archive(*args, **kwargs):
        snapshots.append(deepcopy(c.health()))
        assert c.health()['completed_units'] == c.health()['total_units'] == 2
        assert c.health()['status'] == 'awaiting_archive'

    c.publish = publish
    monkeypatch.setattr('empire.features.financial_statements.collector.prefetch_units', prefetch)
    monkeypatch.setattr('empire.features.financial_statements.collector.wait_for_archive', archive)
    await c.execute()
    assert snapshots[0]['completed_units'] == resume
    assert all(s['total_units'] == 2 for s in snapshots)
    assert c.health()['completed_units'] == 2
    assert c.health()['status'] == 'complete'


@pytest.mark.asyncio
async def test_failed_publish_does_not_advance_stock_progress(monkeypatch):
    c = ThsStatementCollector('income')
    c.query = SimpleNamespace(securities=AsyncMock(return_value=[dict(market='SZ',code='000001')]))
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision':0,'cursor':{}}))
    c.records = SimpleNamespace(sanitize_text=str,add_error=AsyncMock())
    c.publish = AsyncMock(side_effect=RuntimeError('publish failed'))
    @asynccontextmanager
    async def prefetch(*args, **kwargs):
        async def results():
            yield 0, SimpleNamespace(resolve=AsyncMock(return_value=([],None,None)))
        yield results()
    monkeypatch.setattr('empire.features.financial_statements.collector.prefetch_units',prefetch)
    with pytest.raises(RuntimeError,match='publish failed'):
        await c.execute()
    assert c.health()['completed_units'] == 0
    assert c.health()['total_units'] == 1
    assert c.health()['status'] == 'error'
