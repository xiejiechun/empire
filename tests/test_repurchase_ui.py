import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.contracts.repurchases import normalize  # noqa: E402
from empire.plugins.ui.repurchases import RepurchasePage, RepurchaseUiPlugin  # noqa: E402
from tests.test_repurchases import source_row  # noqa: E402


def test_lazy_page_draft_cursor_details_refresh_and_disposal():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke), shutting_down=False)
    spec = RepurchaseUiPlugin().create_pages()[0]
    assert spec.catalogued and spec.management.context.task_id == 'eastmoney-repurchases'
    assert not pending
    page = RepurchasePage(shell)
    page.timer.stop()
    row = normalize(source_row())
    try:
        page.show()
        app.processEvents()
        page.tick()
        page.code.setText('600000')
        pending[-1][1].set_result(dict(rows=[row], next=['2025-01-01', '1']))
        page.tick()
        assert page.code.text() == '600000' and page.applied[0] == ''
        page.table.selectRow(0)
        page.tick()
        assert pending[-1][0][-2:] == ('detail', '1')
        pending[-1][1].set_result(row)
        page.tick()
        assert '实施中' in page.reader.toPlainText()
        assert '注销生效日' in page.reader.toPlainText()
        page.find()
        page.tick()
        # Refresh loads details again even when selection identity is unchanged.
        details = [f for args, f in pending if args[-2] == 'detail']
        assert len(details) == 2
        page.code.setText('保留草稿')
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.code.text() == '保留草稿' and page.applied[0] == '600000'
        page.hide()
        calls = len(pending)
        page.tick()
        assert len(pending) == calls
        shell.shutting_down = True
        page.tick()
        assert not page.timer.isActive()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
