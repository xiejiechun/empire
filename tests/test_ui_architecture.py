"""Guard the UI's plugin boundaries and independently managed page lifetimes."""
import ast
import time
from pathlib import Path

from empire.bootstrap import build_manager
from empire.core.manager import PluginManager
from empire.core.runtime import Runtime


def test_ui_modules_remain_small_and_shell_has_no_business_imports():
    source = Path(__file__).resolve().parents[1] / "src" / "empire"
    ui_files = [*(source / "desktop").rglob("*.py"), *(source / "plugins" / "ui").rglob("*.py")]
    for path in ui_files:
        text = path.read_text(encoding="utf-8")
        if path.name == "tasks.py":
            assert '"sina-news"' not in text and '"cninfo-calendar"' not in text
        assert len(text.splitlines()) <= 350, f"Split UI responsibilities before growing {path.name}"
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if path.parent.name == "desktop":
                assert not node.module.startswith("empire.plugins."), path
            if path.name == "common.py":
                assert not node.module.startswith("empire.plugins."), path
            # Shared controls must not be imported from a business page.
            assert node.module != "empire.plugins.ui.collection", path
            if node.module == "empire.plugins.ui.catalog":
                assert all(alias.name == "DataCatalogPage" for alias in node.names), path


def test_ui_plugin_stop_restart_and_restore_preserve_other_contributions(tmp_path, monkeypatch):
    cfg = {"redis": {}, "mysql": {}, "archive": {}, "ingest": {}, "rate_groups": {}}
    all_plugins = build_manager(cfg)
    plugins = [entry.plugin for ident, entry in all_plugins.entries.items() if ident.startswith("ui.")]
    monkeypatch.setattr("empire.core.runtime.user_data_dir", lambda: tmp_path)
    runtime = Runtime(lambda: PluginManager(plugins), {})

    def wait_pages(expected):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pages = runtime.page_contributions()
            if {p.id for p in pages} == expected:
                assert len(pages) == len(expected)
                return
            time.sleep(.02)
        raise AssertionError(f"Expected {expected}, got {runtime.page_contributions()}")

    all_ids = {"home", "catalog", "stocks", "news", "calendar", "collection", "history",
               "sites", "system", "plugins", "help", "proxies", "downloads"}
    runtime.start()
    try:
        wait_pages(all_ids)
        runtime.command("stop", "ui.collection").result(timeout=5)
        wait_pages(all_ids - {"collection", "history", "sites"})
        assert runtime.manager.entries["ui.news"].state == "RUNNING"
        runtime.command("start", "ui.collection").result(timeout=5)
        wait_pages(all_ids)
        for plugin in plugins:
            runtime.command("stop", plugin.manifest.id).result(timeout=5)
        wait_pages(set())
        runtime.command("restore_ui").result(timeout=5)
        wait_pages(all_ids)
    finally:
        runtime.command("shutdown").result(timeout=5)
        runtime.thread.join(timeout=5)
    assert runtime.closed.is_set()
