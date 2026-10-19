"""Business handlers and page factories are explicit, stateless assembly inputs."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.confirmation import ConfirmationContribution
from empire.features.builtin import builtin_bundles, confirmation_handlers
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin
from empire.plugins.ui.workspace import WorkspaceUiPlugin

CFG = {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}


def stock_bundle():
    return next(bundle for bundle in builtin_bundles(CFG) if bundle.id == 'stocks')


def test_real_catalog_declares_exact_stateless_stock_handler():
    from empire.features.stocks.confirmation import stock_status
    handlers = confirmation_handlers(builtin_bundles(CFG))
    assert handlers == {'stocks.snapshot': stock_status}
    assert stock_status.__closure__ is None


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unused', 'wrong_owner'])
def test_invalid_handler_ownership_fails_before_services_are_constructed(change):
    stock = stock_bundle()
    if change == 'missing':
        bundles = [replace(stock, confirmations=())]
    elif change == 'duplicate':
        bundles = [replace(stock, confirmations=stock.confirmations * 2)]
    elif change == 'unused':
        bundles = [replace(stock, datasets=())]
    else:
        bundles = [replace(stock, confirmations=()),
                   replace(stock, id='other', plugins=(), tasks=(), datasets=())]
    with pytest.raises(ValueError, match='归档确认'):
        confirmation_handlers(bundles)


def test_no_stock_catalog_needs_no_stock_handler_or_implicit_feature_import():
    assert confirmation_handlers([]) == {}
    with pytest.raises(ValueError, match='贡献'):
        ConfirmationContribution('stocks.snapshot', None)


@pytest.mark.asyncio
async def test_shared_provider_forwards_exact_store_and_identity_arguments():
    seen = []
    result = {'status': 'complete', 'snapshot_id': 's'}

    async def handler(*args):
        seen.append(args)
        return result

    provider = ArchiveConfirmationPlugin({'stocks.snapshot': handler})
    mysql, redis = object(), object()
    await provider.start(SimpleNamespace(get={'mysql.store': mysql, 'redis.store': redis}.__getitem__))
    assert await provider.stock_status('sina', 'job', 'project', 's') is result
    assert seen == [(mysql, redis, 'sina', 'job', 'project', 's')]
    await provider.stop()
    assert provider.mysql is provider.redis is None
    assert provider.health() == {'status': 'stopped'}


@pytest.mark.parametrize('failure', [RuntimeError('storage failure'), asyncio.CancelledError()])
@pytest.mark.asyncio
async def test_handler_failure_and_cancellation_are_not_fabricated_as_success(failure):
    async def handler(*args):
        raise failure
    provider = ArchiveConfirmationPlugin({'stocks.snapshot': handler})
    with pytest.raises(type(failure)) as observed:
        await provider.stock_status('sina', 'job', 'project', 'snapshot')
    assert observed.value is failure


@pytest.mark.asyncio
async def test_missing_injected_handler_never_falls_back_to_business_import():
    with pytest.raises(RuntimeError, match='未通过业务贡献注入'):
        await ArchiveConfirmationPlugin().stock_status('sina', 'job', 'project', 'snapshot')


def test_workspace_factory_is_lazy_and_returns_original_contributions():
    called, pages = [], (object(), object())
    def factory():
        called.append(True)
        return pages
    plugin = WorkspaceUiPlugin(factory)
    assert not called
    assert plugin.create_pages() is pages
    assert called == [True]
    assert plugin.manifest.id == 'ui.workspace'


@pytest.mark.parametrize('store', ['mysql', 'redis'])
@pytest.mark.parametrize('failure', [RuntimeError('actual store failure'), asyncio.CancelledError()])
@pytest.mark.asyncio
async def test_real_injected_stock_handler_propagates_storage_failure(store, failure):
    from empire.features.stocks.confirmation import stock_status
    provider = ArchiveConfirmationPlugin({'stocks.snapshot': stock_status})
    provider.redis = SimpleNamespace(prefix='owned', client=SimpleNamespace(get=AsyncMock(return_value=None)))
    provider.mysql = SimpleNamespace(control=AsyncMock(return_value={'progress': {}}))
    if store == 'mysql':
        provider.mysql.control.side_effect = failure
    else:
        provider.redis.client.get.side_effect = failure
    with pytest.raises(type(failure)) as caught:
        await provider.stock_status('sina', 'job', 'project', 'snapshot')
    assert caught.value is failure


def test_real_workspace_contributions_remain_lazy_with_exact_page_metadata(monkeypatch):
    from PySide6.QtWidgets import QWidget

    from empire.features.data_browser.bundle import bundle
    def forbidden(*args, **kwargs):
        raise AssertionError('page created while collecting declarations')
    monkeypatch.setattr(QWidget, '__init__', forbidden)
    contribution = bundle(CFG).plugins[0]
    assert contribution.ordinal == 14800
    pages = contribution.value.create_pages()
    assert [(p.id, p.title, p.group, p.order, p.cache_policy, p.top_level) for p in pages] == [
        ('home', '总览', '工作台', 0, 'lru', True),
        ('catalog', '数据目录', '数据浏览', -1, 'lru', False)]

