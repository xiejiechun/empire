import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.industries import IndustryPage, IndustryUiPlugin  # noqa: E402


def test_lazy_industry_page_query_does_not_overwrite_draft():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
                            navigate_management=lambda _: None, shutting_down=False)
    plugin = IndustryUiPlugin()
    contribution = plugin.create_pages()[0]
    assert contribution.catalogued and contribution.management.context.task_id == 'ths-industries'
    assert not pending
    page = IndustryPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        assert len(pending) == 1
        page.search.setText('未提交草稿')
        pending[0][1].set_result(dict(rows=[dict(industry_code='881155', industry_name='银行',
            market='SZ', code='000001', name='平安银行')], total=1, industry_count=1, publication={'batch_id': 'a'}))
        page.tick()
        assert page.search.text() == '未提交草稿'
        assert page.table.item(0, 3).text() == '000001'
        page.hide()
        page.dirty = True
        page.tick()
        assert len(pending) == 1
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.search.text() == '未提交草稿'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
