import os
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.collection_views.tasks import TasksPage  # noqa: E402


def test_shift_select_batch_refresh_and_partial_failure():
    app = QApplication.instance() or QApplication([])
    calls = []
    future = Future()

    def invoke(*args):
        calls.append(args)
        return future

    page = TasksPage(SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={}))
    page.timer.stop()
    job = dict(name='任务', description='说明', policy=dict(enabled=True, mode='manual',
        interval_seconds=300, daily_time='18:00', request_retries=2), active=None,
        next_due=None, last_status='idle', rate_group='source', progress={})
    page.data = dict(jobs=[dict(deepcopy(job), id=str(i)) for i in range(4)], history=[])
    try:
        page.render()
        page.resize(1000, 700)
        page.show()
        app.processEvents()
        page.interval.setValue(37)
        menu = page.task_menu
        QTest.mouseClick(menu.viewport(), Qt.MouseButton.LeftButton,
                         pos=menu.visualItemRect(menu.task_items['0']).center())
        QTest.mouseClick(menu.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         menu.visualItemRect(menu.task_items['2']).center())
        assert menu.selected_ids() == ['0', '1', '2']
        page.render()
        assert menu.selected_ids() == ['0', '1', '2']
        QTest.mouseClick(menu.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                         menu.visualItemRect(menu.task_items['1']).center())
        assert menu.selected_ids() == ['0', '2']
        page.render()
        assert menu.selected_ids() == ['0', '2']
        menu.task_items['1'].setSelected(True)
        assert page.job_drafts['0']['interval_seconds'] == 37
        page.batch_start.click()
        assert calls[-1] == ('collection.control', 'batch', 'start', ['0', '1', '2'])
        assert not page.batch_stop.isEnabled()
        future.set_result(dict(operation='start', results=[
            dict(id='0', status='success', message='已启动'),
            dict(id='1', status='skipped', message='任务正在执行'),
            dict(id='2', status='failed', message='插件未启用')]))
        page._finish_action()
        page._update_buttons()
        assert '成功 1，跳过 1，失败 1' in page.batch_feedback.text()
        assert '插件未启用' in page.batch_feedback.text()
        long_result = dict(operation='stop', results=[
            dict(id=str(i), status='failed', message='失败\n' * 100) for i in range(43)])
        assert len(page.batch_result(long_result).splitlines()) == 5
        assert '另 40 项' in page.batch_result(long_result)
        menu.task_items['3'].setSelected(True)
        page.data['jobs'] = page.data['jobs'][2:]
        page.render()
        assert menu.selected_ids() == ['2', '3']
        page.batch_stop.click()
        assert calls[-1] == ('collection.control', 'batch', 'stop', ['2', '3'])
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
