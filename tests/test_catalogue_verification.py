"""Observer ownership and same-count/different-content counterexamples, no network."""
import importlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from empire.plugins.collection.unit_prefetch import DeferredResponse


@pytest.fixture
def observer(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('catalogue_verification')


@pytest.mark.asyncio
async def test_deferred_observer_preserves_close_and_ordered_consumption(observer):
    response, remember = Mock(), Mock()
    rows = [['000001', '甲']]
    consume = AsyncMock(return_value=rows)
    deferred = DeferredResponse(response, consume)
    fetch = observer.observe_fetch(AsyncMock(return_value=deferred), remember)
    actual = await fetch('url', 'parser', defer=True)
    assert actual is deferred
    remember.assert_not_called()
    consume.assert_not_awaited()
    assert await actual.consume() is rows
    remembered = remember.call_args.args[1]
    rows[0][1] = '乙'
    assert remembered == [['000001', '甲']]
    response.close.assert_not_called()
    actual.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_failed_or_cancelled_consumer_does_not_invent_source_evidence(observer):
    response, remember = Mock(), Mock()
    deferred = DeferredResponse(response, AsyncMock(side_effect=ValueError('source invalid')))
    fetch = observer.observe_fetch(AsyncMock(return_value=deferred), remember)
    value = await fetch('url', 'parser')
    with pytest.raises(ValueError, match='source invalid'):
        await value.consume()
    remember.assert_not_called()
    value.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_same_count_different_content_refused_before_redis_and_failed_publish_not_recorded(observer):
    original, published = AsyncMock(return_value={'revision': 1}), []
    envelope = SimpleNamespace(dataset='x', business_key='x', raw_payload={'rows': ['wrong']})

    def check(value):
        observer.require(value.raw_payload['rows'] == ['expected'], 'content mismatch')

    publish = observer.observe_publish(original, check, published)
    with pytest.raises(ValueError, match='content mismatch'):
        await publish([envelope], expected_revision=0)
    original.assert_not_awaited()
    envelope.raw_payload['rows'] = ['expected']
    original.side_effect = RuntimeError('Redis failed')
    with pytest.raises(RuntimeError, match='Redis failed'):
        await publish([envelope], expected_revision=0)
    assert not published


@pytest.mark.asyncio
async def test_public_pagination_repeated_cursor_is_not_complete(observer):
    read = AsyncMock(return_value=dict(rows=[{'code': 'a'}], next=['a']))
    with pytest.raises(ValueError, match='游标重复'):
        await observer.public_pages(read)


@pytest.mark.asyncio
async def test_nonzero_pending_or_isolation_refuses_acceptance(observer):
    worker = SimpleNamespace(blocked=False, blocked_projects=[], isolated=[])
    store = SimpleNamespace(client=SimpleNamespace(xlen=AsyncMock(return_value=1)), stream='owned')
    manager = SimpleNamespace(registry=SimpleNamespace(get=lambda key: store if key == 'redis.store' else worker))
    with pytest.raises(ValueError, match='待归档'):
        await observer.require_drained(manager)
    store.client.xlen.return_value = 0
    worker.isolated = ['owned-message']
    with pytest.raises(ValueError, match='归档隔离'):
        await observer.require_drained(manager)


def test_native_index_negative_amount_is_retained():
    from empire.features.yuanhang_indices.contract import number
    from empire.features.yuanhang_indices.quality import volume_amount_valid
    assert number(Decimal('-1')) == '-1'
    assert not volume_amount_valid([Decimal('1'), Decimal('-1')])
