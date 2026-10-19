import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.preparation import CheckEvidence
from empire.features.preparation.catalog import REQUIREMENTS
from empire.features.preparation.query import PreparationPlugin
from tests.test_preparation import contribution


@pytest.fixture(autouse=True)
def artifact(monkeypatch):
    monkeypatch.setattr('empire.features.preparation.query.load_evidence', lambda: ({}, '本版本测试尚未执行'))


async def test_catalog_and_progress_are_available_before_slow_source_finishes():
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow():
        entered.set()
        await release.wait()
        return (CheckEvidence('keys', 'pass', '已核验'),)
    service = SimpleNamespace(preparation_check=AsyncMock(side_effect=slow))
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional={'stocks.query': service}.get))
    task = asyncio.create_task(plugin.report())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        partial = await plugin.snapshot()
        assert len(partial['rows']) == len(REQUIREMENTS)
        assert partial['checking'] and not task.done()
        first = partial['rows'][0]
        assert first['data'] == 0 and not first['complete']
        for _ in range(3):
            assert (await plugin.snapshot())['checking']
        service.preparation_check.assert_awaited_once()
        assert await plugin.snapshot({'codes': ['601139'], 'purpose': 'analysis'}) is None
    finally:
        release.set()
    final = await task
    assert not final['checking']
    assert final['checked_requirements'] == len(REQUIREMENTS)
    assert final['rows'][0]['data'] == 1


async def test_cancelled_report_releases_owner_and_never_marks_pending_data_ready():
    entered = asyncio.Event()
    async def slow():
        entered.set()
        await asyncio.Event().wait()
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional={'stocks.query': SimpleNamespace(preparation_check=slow)}.get))
    task = asyncio.create_task(plugin.report())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = await plugin.snapshot()
    assert not snapshot['checking'] and not snapshot['rows'][0]['complete']
    await plugin.stop()


async def test_ui_renders_partial_catalog_while_full_query_is_pending():
    from PySide6.QtWidgets import QApplication

    from empire.features.preparation.ui import PreparationPage
    app = QApplication.instance() or QApplication([])
    plugin = PreparationPlugin([])
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    report = await plugin.report({'codes': ['601139'], 'purpose': 'analysis'})
    report.update(checking=True, checked_requirements=2, current_requirement='利润表')
    full = Future()
    calls = []
    class Runtime:
        def invoke(self, capability, method, *args):
            calls.append(method)
            if method == 'report':
                return full
            value = Future()
            value.set_result(report)
            return value
    page = PreparationPage(SimpleNamespace(cfg={}, shutting_down=False, runtime=Runtime()))
    page.timer.stop()
    page.show()
    app.processEvents()
    page.reload()
    page.tick()
    page.tick()
    assert not full.done() and page.table.rowCount() > 0
    assert '已检查 2' in page.summary.text() and '利润表' in page.summary.text()
    assert not page.refresh_button.isEnabled()
    assert calls.count('report') == 1
    page.query_scope.close()
    page.deleteLater()
    app.processEvents()
