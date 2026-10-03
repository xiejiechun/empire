import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.intraday import IntradayPage, IntradayUiPlugin  # noqa: E402
from tests.test_kaipanla_intraday import row  # noqa: E402


def test_lazy_query_preserves_new_drafts_and_all_same_minute_points():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
                            navigate_management=lambda _: None, shutting_down=False)
    contribution = IntradayUiPlugin().create_pages()[0]
    assert contribution.catalogued and contribution.management.context.task_id == 'kaipanla-intraday'
    assert not pending
    page = IntradayPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.find()
        page.tick()
        assert len(pending) == 1
        page.code.setText('600519')
        pending[0][1].set_result(dict(data=row(), observed_at=None))
        page.tick()
        assert page.code.text() == '600519'
        assert page.auction.rowCount() == 5
        assert page.auction.item(3, 4).text() == '5'
        page.hide()
        page.dirty = True
        page.tick()
        assert len(pending) == 1
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.code.text() == '600519'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
