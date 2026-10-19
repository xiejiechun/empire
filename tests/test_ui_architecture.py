"""Guard the UI's plugin boundaries and independently managed page lifetimes."""
import time
from pathlib import Path

from empire.bootstrap import build_manager
from empire.core.manager import PluginManager
from empire.core.runtime import Runtime
from scripts.ui_architecture_contract import check_ui_architecture


def test_ui_modules_remain_small_and_shell_has_no_business_imports():
    root = Path(__file__).resolve().parents[1]
    errors = check_ui_architecture(root)
    assert not errors, '\n'.join(errors)


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

    performance_ids = {'earnings_forecast', 'earnings_quick', 'earnings_disclosure', 'earnings_report', 'holder_count', 'shareholder_changes'}
    all_ids = {*performance_ids, "ths_capital", "unlock_industries", "unlocks", "top_holders", "float_holders", "bond_holders", "repurchases", "listing_status", "listings", "dividends", "additional_issues", "rights_issues", "home", "catalog", "stocks", "news", "calendar", "collection", "history",
               "archived_tasks", "sites", "system", "plugins", "help", "proxies", "downloads", "preparation", "suspensions",
               "income", "balance", "cashflow", "industries", "indices", "index_prices", "names_company", "names_security", "st_implementation", "st_removal", "adjustment",
               *('kaipanla_' + k for k in ('trend','auction','volume','trades','entrust','large_order','quote'))}
    all_ids.update('rules_' + k for k in ('limit_rules', 'settlement_rules', 'lot_rules', 'tick_rules', 'sessions', 'stamp_duty', 'transfer_fee'))
    runtime.start()
    try:
        wait_pages(all_ids)
        runtime.command('stop', 'ui.ths_capital').result(timeout=5)
        wait_pages(all_ids - {'ths_capital'})
        assert runtime.manager.entries['ui.news'].state == 'RUNNING'
        runtime.command('start', 'ui.ths_capital').result(timeout=5)
        wait_pages(all_ids)
        for kind in ('top_holders', 'float_holders', 'bond_holders'):
            runtime.command('stop', 'ui.' + kind).result(timeout=5)
            wait_pages(all_ids - {kind})
            assert runtime.manager.entries['ui.news'].state == 'RUNNING'
            runtime.command('start', 'ui.' + kind).result(timeout=5)
            wait_pages(all_ids)
        for kind in performance_ids:
            runtime.command('stop', 'ui.tdx_' + kind).result(timeout=5)
            wait_pages(all_ids - {kind})
            assert runtime.manager.entries['ui.news'].state == 'RUNNING'
            runtime.command('start', 'ui.tdx_' + kind).result(timeout=5)
            wait_pages(all_ids)
        runtime.command('stop', 'ui.repurchases').result(timeout=5)
        wait_pages(all_ids - {'repurchases'})
        assert runtime.manager.entries['ui.news'].state == 'RUNNING'
        runtime.command('start', 'ui.repurchases').result(timeout=5)
        wait_pages(all_ids)
        runtime.command('stop', 'ui.rules_limit_rules').result(timeout=5)
        wait_pages(all_ids - {'rules_limit_rules'})
        assert runtime.manager.entries['ui.rules_lot_rules'].state == 'RUNNING'
        runtime.command('start', 'ui.rules_limit_rules').result(timeout=5)
        wait_pages(all_ids)
        runtime.command("stop", "ui.collection").result(timeout=5)
        wait_pages(all_ids - {"collection", "archived_tasks", "history", "sites"})
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
