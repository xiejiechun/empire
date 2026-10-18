"""Offscreen catalog layout checks using formal read-only queries; no collectors or archiver."""
import json
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from empire.bootstrap import build_manager  # noqa: E402
from empire.contracts.ui import NavigationContext  # noqa: E402
from empire.core.config import load_config, project_root  # noqa: E402
from empire.core.manager import PluginManager  # noqa: E402
from empire.core.runtime import Runtime  # noqa: E402
from empire.core.time import CHINA  # noqa: E402
from empire.desktop.interaction import install_input_rules  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402


def run():
    cfg, root = load_config(), project_root()
    out = root/'build/preview-ui'
    out.mkdir(parents=True, exist_ok=True)
    def factory():
        manager = build_manager(cfg)
        plugins = []
        for ident, entry in manager.entries.items():
            wanted = (ident.startswith('data.') and ident != 'data.preparation'
                      or ident.startswith('ui.') or ident == 'infra.mysql')
            if wanted:
                entry.plugin.manifest = replace(entry.plugin.manifest, autostart=True)
                plugins.append(entry.plugin)
        return PluginManager(plugins, redactor=manager.redactor)
    runtime = Runtime(factory, cfg)
    runtime.state_file = out/'read-only-no-preferences.json'
    runtime.start()
    expected = {p.id for e in build_manager(cfg).entries.values() if e.plugin.manifest.id.startswith('ui.')
                for p in e.plugin.create_pages() if p.catalogued}
    assert {'top_holders', 'float_holders', 'bond_holders'} <= expected
    app = QApplication.instance() or QApplication([])
    for name in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'):
        font = Path('C:/Windows/Fonts')/name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    install_input_rules(app)
    def wait(seconds=1):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(.02)
    window = None
    report = dict(mode='offscreen real SQL, not visible EXE acceptance', pages=[], errors=[])
    try:
        for _ in range(100):
            if {p.id for p in runtime.page_contributions() if p.catalogued} == expected:
                break
            wait(.1)
        window = MainWindow(runtime, cfg)
        window.timer.stop()
        window.show()
        pages = [p for p in runtime.page_contributions() if p.catalogued]
        assert {p.id for p in pages} == expected
        for entry in pages:
            window.resize(1320, 900)
            window.navigate(entry.id)
            page = window.page_widgets[entry.id]
            wait(1)
            if entry.id.startswith('kaipanla_'):
                candidates = runtime.invoke('stocks.query', 'candidates', '', entry.id, 1).result(10)
                if candidates:
                    page.apply_navigation_context(NavigationContext(unified_code=candidates[0]['unified_code']))
                    wait(1)
            elif entry.id == 'index_prices':
                indices = runtime.invoke('indices.query', 'browse', 'indices', '', None, 1).result(10)
                if indices['rows']:
                    page.apply_navigation_context(NavigationContext(index_code=indices['rows'][0]['index_code'], source='ths'))
                    wait(1)
            elif entry.id == 'adjustment':
                candidates = runtime.invoke('stocks.query', 'candidates', '', 'kaipanla_quote', 1).result(10)
                if candidates:
                    end = runtime.invoke('kaipanla_quote.query', 'archived_date', candidates[0]['unified_code'][-2:],
                        candidates[0]['unified_code'][:6], datetime.now(CHINA).date().isoformat(), 0).result(10)
                    if end:
                        start = (datetime.fromisoformat(end).date()-timedelta(days=30)).isoformat()
                        page.apply_navigation_context(NavigationContext(unified_code=candidates[0]['unified_code'], start=start, end=end))
                        wait(1)
            elif entry.id == 'suspensions':
                page.all_dates.setChecked(True)
                wait(1)
            elif entry.id in ('listings', 'income', 'balance', 'cashflow'):
                candidates = runtime.invoke('stocks.query', 'candidates', '', entry.id, 1).result(10)
                if candidates:
                    page.apply_navigation_context(NavigationContext(unified_code=candidates[0]['unified_code']))
                    wait(1)
            # Page timers may first submit at 1s, then apply the result on their next tick.
            # Wait for the displayed loading phase to finish before claiming a query check.
            for _ in range(100):
                labels = [w.text() for w in page.findChildren(QLabel) if w.isVisible()]
                if not any(t.startswith(('正在读取', '正在加载', '正在查询', '正在核对', '等待读取')) for t in labels):
                    break
                wait(.1)
            for width, height in ((1320, 900), (880, 600)):
                window.resize(width, height)
                wait(.15)
                window.grab().save(str(out/f'{entry.id}-{width}.png'))
            labels = [w.text() for w in page.findChildren(QLabel) if w.isVisible()]
            failures = [t for t in labels if any(x in t for x in ('查询失败', '加载失败', '读取失败'))
                        or t.startswith(('正在读取', '正在加载', '正在查询', '正在核对', '等待读取'))]
            report['pages'].append(dict(id=entry.id, labels=labels, sizes=[1320, 880]))
            report['errors'].extend(dict(page=entry.id, text=t) for t in failures)
            print(entry.id, 'FAIL' if failures else 'checked', flush=True)
        assert not any(e.state == 'RUNNING' for k, e in runtime.manager.entries.items()
                       if k.startswith('collector.') or k in ('archive.worker', 'collection.control'))
        report['passed'] = not report['errors']
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        if report['errors']:
            raise RuntimeError('真实查询离屏预览失败，见build/preview-ui/report.json')
    finally:
        if window:
            window.shutting_down = True
            window.can_close = True
            window.page_registry.deactivate_current()
            window.close()
        runtime.command('shutdown').result(20)
        runtime.thread.join(20)
        app.processEvents()


if __name__ == '__main__':
    run()
