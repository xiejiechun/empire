"""Holder UI contributions stay independently stoppable and lazy after packaging."""
import socket

from empire.bootstrap import build_manager
from empire.features.holders import ui


async def test_holder_pages_remain_independent_without_starting_data_or_collectors(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Page providers must not create widgets or open connections')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(ui, 'HolderPage', forbidden)
    manager = build_manager({'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}})
    try:
        await manager.start('ui.top_holders')
        assert set(manager.registry.values) == {'ui.pages.top_holders'}
        await manager.start('ui.float_holders')
        floating = manager.registry.get('ui.pages.float_holders')
        assert floating[0].id == 'float_holders'
        assert floating[0].management.context.task_id == 'ths-holders'
        await manager.stop('ui.top_holders')
        assert set(manager.registry.values) == {'ui.pages.float_holders'}
        assert manager.registry.get('ui.pages.float_holders') is floating
        await manager.start('ui.bond_holders')
        await manager.stop('ui.float_holders')
        assert set(manager.registry.values) == {'ui.pages.bond_holders'}
        assert manager.registry.get('ui.pages.bond_holders')[0].id == 'bond_holders'
        assert all(entry.context is None and entry.state == 'STOPPED'
                   for ident, entry in manager.entries.items() if ident != 'ui.bond_holders')
    finally:
        await manager.shutdown()
    assert not manager.registry.values
    assert all(entry.context is None and entry.state == 'STOPPED'
               for entry in manager.entries.values())
