"""Headless metadata must keep task ownership without importing desktop widgets."""
import subprocess
import sys
from pathlib import Path

from empire.bootstrap import build_manager
from empire.plugins.ui.plugin import UiPlugin

ROOT = Path(__file__).resolve().parents[1]


def test_backend_assembly_does_not_import_widget_runtime():
    code = "from empire.bootstrap import build_manager; import sys; m=build_manager(dict(redis={},mysql={},archive={},ingest={},rate_groups={})); assert len(m.entries['collection.control'].plugin.definitions)==52; assert not any(k.startswith('PySide6.QtWidgets') for k in sys.modules)"
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True)


async def test_metadata_lifecycle_and_task_ownership():
    manager = build_manager(dict(redis={},mysql={},archive={},ingest={},rate_groups={}))
    tasks = manager.entries['collection.control'].plugin.definitions
    pages = []
    for entry in manager.entries.values():
        plugin = entry.plugin
        if isinstance(plugin, UiPlugin):
            declarations = tuple(plugin.create_pages())
            await plugin.start(None)
            assert plugin.pages == declarations
            pages.extend(declarations)
            await plugin.stop()
            assert plugin.pages == ()
    assert len({p.id for p in pages}) == len(pages)
    for page in pages:
        assert not hasattr(page, 'factory')
        if page.management and page.management.context.task_id:
            assert page.management.context.task_id in tasks


def test_retired_sources_absent():
    assert not (ROOT / 'Empire.spec').exists()
    assert not (ROOT / 'src/empire/desktop/window.py').exists()
