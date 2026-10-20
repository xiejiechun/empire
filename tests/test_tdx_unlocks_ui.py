import os
from concurrent.futures import Future
from types import SimpleNamespace

from empire.features.unlocks.ui import UnlockUiPlugin
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


def test_filter_and_page_changes_detach_running_detail_and_old_links():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    parents, children = normalized()
    requests = []

    def invoke(capability, method, *args):
        future = Future()
        # A running read may finish after cancellation was requested.
        future.set_running_or_notify_cancel()
        requests.append((method, args, future))
        return future

    contribution, = UnlockUiPlugin().create_pages()
    page = contribution.factory(SimpleNamespace(runtime=SimpleNamespace(config={}, invoke=invoke)))
    page.show()
    page.timer.stop()
    page.tick()
    requests[-1][2].set_result(dict(rows=parents, next=['cursor']))
    page.tick()
    page.open_detail(QUrl('unlock:' + parents[0]['group_key']))
    late_detail = requests[-1][2]
    page.code.setText('000000')
    page.find()
    assert page.group == '' and page.detail_future is None
    assert 'unlock:' not in page.reader.toHtml()
    assert not page.previous.isEnabled() and not page.next.isEnabled()
    late_detail.set_result(children)
    page.tick()
    requests[-1][2].set_result(dict(rows=[], next=None))
    page.tick()
    assert '当前条件无已归档记录' in page.reader.toPlainText()
    assert '来源股东' not in page.detail.toPlainText()

    page.open_detail(QUrl('unlock:' + parents[0]['group_key']))
    requests[-1][2].set_result(children)
    page.tick()
    assert '来源股东' in page.detail.toPlainText()
    page.next_cursor = ['cursor']
    page.move(True)
    assert page.after == ['cursor'] and page.history == [None]
    assert '来源股东' not in page.detail.toPlainText()
    assert 'unlock:' not in page.reader.toHtml()
    page.open_detail(QUrl('unlock:' + parents[0]['group_key']))
    hidden_detail = requests[-1][2]
    page.hide()
    hidden_detail.set_result(children)
    page.show()
    page.timer.stop()
    page.tick()
    assert page.group == '' and '来源股东' not in page.detail.toPlainText()
    page.hide()
    page.deleteLater()
    app.processEvents()


def test_refresh_preserves_scroll_for_same_query():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    parents, _ = normalized()

    def invoke(capability, method, *args):
        future = Future()
        future.set_result(dict(rows=parents * 100, next=None))
        return future

    contribution, = UnlockUiPlugin().create_pages()
    page = contribution.factory(SimpleNamespace(runtime=SimpleNamespace(config={}, invoke=invoke)))
    page.resize(1100, 800)
    page.show()
    page.timer.stop()
    app.processEvents()
    page.tick()
    page.tick()
    app.processEvents()
    page.reader.verticalScrollBar().setValue(1000)
    before = page.reader.verticalScrollBar().value()
    assert before > 0
    page.find()
    app.processEvents()
    page.tick()
    page.tick()
    app.processEvents()
    assert page.reader.verticalScrollBar().value() == before
    page.hide()
    page.deleteLater()
    app.processEvents()
