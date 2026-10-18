import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.kaipanla_products import KaipanlaProductUiPlugin, ProductPage  # noqa: E402
from tests.test_kaipanla_products import business_row  # noqa: E402


def test_lazy_query_preserves_new_drafts_and_all_same_minute_points():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
                            navigate_management=lambda _: None, shutting_down=False)
    contribution = KaipanlaProductUiPlugin('auction').create_pages()[0]
    assert contribution.catalogued and contribution.management.context.task_id == 'kaipanla-auction'
    assert not pending
    page = ProductPage(shell, 'auction')
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.code.setText('000001')
        page.find()
        page.tick()
        assert len(pending) == 1
        page.code.setText('600519')
        pending[0][1].set_result(dict(data=business_row('auction'), observed_at=None))
        page.tick()
        assert page.code.text() == '600519'
        assert page.table.rowCount() == 5
        assert '000001.SZ' in page.status.text()
        assert page.table.item(3, 4).text() == '5'
        page.hide()
        page.dirty = True
        page.tick()
        assert len(pending) == 1
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.code.text() == '600519'
        page.show()
        page.find()
        page.tick()
        pending[-1][1].set_result(None)
        page.tick()
        assert page.total == 0 and page.table.rowCount() == 0 and page.next_cursor is None
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
