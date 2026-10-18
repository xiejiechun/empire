"""Lazy reads, preserved filter drafts and readable complete details."""
import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.collectors.ths_capital_source import parse  # noqa: E402
from empire.plugins.ui.ths_capital import CapitalPage, CapitalPageUiPlugin, content  # noqa: E402
from tests.test_ths_capital import STOCK, source  # noqa: E402


def test_lazy_query_draft_restore_hidden_cancellation_and_complete_details():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke, config={}))
    spec = CapitalPageUiPlugin().create_pages()[0]
    assert spec.catalogued and spec.management.context.task_id == 'ths-capital'
    page = CapitalPage(shell)
    page.timer.stop()
    row = {**parse(source().encode('gb18030'), STOCK)['rows']['capital_funding'][0], 'in_window': True}
    try:
        assert not pending
        page.show()
        app.processEvents()
        page.tick()
        page.code.setText('未保存草稿')
        pending[-1][1].set_result(dict(rows=[row], next=[row[k] for k in ('event_date', 'unified_code', 'record_key')]))
        page.tick()
        assert page.code.text() == '未保存草稿' and pending[-1][0][-2:] == ('capital_funding', row['record_key'])
        pending[-1][1].set_result(row)
        page.tick()
        assert '125000000' in page.reader.toPlainText() and '未知（来源未提供）' in page.reader.toPlainText()
        state = page.save_ui_state()
        page.restore_ui_state(state)
        assert page.code.text() == '未保存草稿'
        # Applying another security must invalidate the previous result cursor
        # before its asynchronous first-page response arrives.
        page.code.setText('000001')
        page.find()
        assert not page.next.isEnabled() and not page.previous.isEnabled()
        page.move(True)
        assert page.after is None
        page.hide()
        before = len(pending)
        page.tick()
        assert len(pending) == before and not page.timer.isActive()
        values = parse(source().encode('gb18030'), STOCK)['rows']
        parent = {**values['capital_encumbrance'][0], 'in_window': True,
                  'releases': [{**r, 'in_window': False} for r in values['capital_release']]}
        page.reader.present(content('capital_encumbrance', parent), identity='sample')
        text = page.reader.toPlainText()
        assert '第一次部分解除' in text and '第二次部分解除' in text and '当前页面未列示' in text
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
