import os
from concurrent.futures import Future
from types import SimpleNamespace

from empire.plugins.ui.unlocks import UnlockUiPlugin
from tests.test_tdx_unlocks import normalized


def test_lazy_drafts_and_shared_details_link(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    contribution, = UnlockUiPlugin().create_pages()
    assert contribution.catalogued and contribution.management.context.task_id == 'tdx-unlocks'
    page = contribution.factory(SimpleNamespace(runtime=SimpleNamespace(config={})))
    parents, children = normalized()
    requests = []
    def invoke(key, runtime, capability, method, *args):
        requests.append((key, capability, method, args))
        future = Future()
        future.set_result(dict(rows=parents, next=None) if method == 'list_records' else children)
        return future
    monkeypatch.setattr(page.scope, 'invoke', invoke)
    monkeypatch.setattr(page.scope, 'result', lambda key, future: future.result())
    page.resize(1100, 800)
    page.show()
    page.timer.stop()
    page.tick()
    page.code.setText('未保存草稿')
    page.tick()
    assert '1642300' in page.reader.toPlainText() and page.code.text() == '未保存草稿'
    assert requests[0][-1][0] == ''
    page.open_detail(QUrl('unlock:' + parents[0]['group_key']))
    page.tick()
    assert requests[-1][-1] == (parents[0]['group_key'],)
    assert '来源股东' in page.detail.toPlainText()
    state = page.save_ui_state()
    page.code.clear()
    page.restore_ui_state(state)
    assert page.code.text() == '未保存草稿'
    page.hide()
    assert not page.timer.isActive()
    page.deleteLater()
    app.processEvents()
