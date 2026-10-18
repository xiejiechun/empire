import os
from concurrent.futures import Future
from types import SimpleNamespace

from empire.plugins.collectors.tdx_unlock_industry_source import parse_month
from empire.plugins.ui.unlock_industries import UnlockIndustryUiPlugin
from tests.test_tdx_unlock_industries import BASIS, MONTHS, source


def test_lazily_created_reader_drafts_and_hidden_timer(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    contribution, = UnlockIndustryUiPlugin().create_pages()
    assert contribution.catalogued and contribution.management.context.task_id == 'tdx-unlock-industries'
    page = contribution.factory(SimpleNamespace(runtime=SimpleNamespace(config={})))
    def invoke(*args):
        future = Future()
        future.set_result(dict(rows=parse_month(source(), MONTHS[0], BASIS), next=None))
        return future
    monkeypatch.setattr(page.scope, 'invoke', invoke)
    monkeypatch.setattr(page.scope, 'result', lambda key, future: future.result())
    page.show()
    page.timer.stop()
    page.tick()
    page.industry.setText('未保存行业草稿')
    page.tick()
    assert '375000' in page.reader.toPlainText() and BASIS in page.reader.toPlainText()
    state = page.save_ui_state()
    page.industry.clear()
    page.restore_ui_state(state)
    assert page.industry.text() == '未保存行业草稿'
    page.hide()
    assert not page.timer.isActive()
    page.deleteLater()
    app.processEvents()
