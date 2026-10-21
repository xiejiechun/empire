"""Interaction regressions; these offscreen tests do not claim desktop acceptance."""
import os
from concurrent.futures import Future
from types import SimpleNamespace

from empire.features.capital_actions.ui import CapitalPage


def test_scope_changes_cancel_old_results_and_recheck_uses_current_fields():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    calls = []
    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future
    runtime = SimpleNamespace(invoke=invoke)
    page = CapitalPage(SimpleNamespace(cfg={}, shutting_down=False, runtime=runtime), 'dividends')
    page.timer.stop()
    panel = page.distribution
    page.code.setText('000001')
    page.start.setText('2026-01-01')
    page.end.setText('2026-10-20')
    panel.calculate()
    first = calls[-1][1]
    assert not panel.button.isEnabled()
    page.end.setText('2026-06-11')
    assert first.cancelled() and panel.future is None
    assert '未检查' in panel.result.toPlainText() and panel.button.isEnabled()
    panel.calculate()
    assert calls[-1][0] == ('dividends.query', 'distribution_summary',
        dict(codes=['000001'], start='2026-01-01', end='2026-06-11'))
    second = calls[-1][1]
    page.code.setText('600000')
    assert second.cancelled() and '未检查' in panel.result.toPlainText()
    panel.calculate()
    assert calls[-1][0][-1]['codes'] == ['600000']
    panel.invalidate()
    panel.yield_button.click()
    assert calls[-1][0][1] == 'dividend_yield'
    assert not panel.button.isEnabled() and not panel.yield_button.isEnabled()
    old_yield = calls[-1][1]
    page.end.setText('2026-10-20')
    assert old_yield.cancelled() and panel.yield_button.isEnabled()
    assert '未检查' in panel.result.toPlainText()
    panel.yield_button.click()
    assert calls[-1][0] == ('dividends.query', 'dividend_yield',
        dict(codes=['600000'], start='2026-01-01', end='2026-10-20'))
    page.query_scope.close()
    page.deleteLater()
    app.processEvents()
