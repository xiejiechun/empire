import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.indices.ui import IndexPage, IndexUiPlugin  # noqa: E402


def test_lazy_index_page_drafts_unavailable_members_and_cursor_navigation():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
                            navigate_management=lambda _: None, shutting_down=False)
    contribution = IndexUiPlugin().create_pages()[0]
    assert contribution.catalogued and contribution.management.context.task_id == 'ths-indices'
    assert not pending
    page = IndexPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.directory.tick()
        page.search.setText('未提交草稿')
        pending[0][1].set_result(dict(rows=[dict(index_code='1A0001', index_name='上证指数',
            source_group='重要', member_count=2, members_available=1)], next=['1A0001']))
        page.directory.tick()
        page.tick()
        pending[-1][1].set_result(dict(rows=[dict(index_code='1A0001', index_name='上证指数', source_code='000001', unified_code='000001.SZ', name='样本', members_available=1)], next=['1A0001', '000001']))
        page.tick()
        assert page.search.text() == '未提交草稿' and page.table.item(0, 0).text() == '1A0001'
        page.forward()
        page.tick()
        assert pending[-1][0][-3] == ['1A0001', '000001']
        pending[-1][1].set_result(dict(rows=[], next=None))
        page.tick()
        page.search.clear()
        page.mode.setCurrentIndex(1)
        page.tick()
        pending[-1][1].set_result(dict(rows=[dict(index_code='399300', index_name='沪深300', source_code='000001',
            unified_code='000001.SZ', name='样本', members_available=0)], next=None))
        page.tick()
        assert page.table.item(0, 5).text() == '历史参考'
        page.search.setText('保留草稿')
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.search.text() == '保留草稿' and page.mode.currentData() == 'reverse'
        page.hide()
        calls = len(pending)
        page.tick()
        assert len(pending) == calls
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
