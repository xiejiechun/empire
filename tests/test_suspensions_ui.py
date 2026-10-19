import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.suspensions.ui import SuspensionsPage, SuspensionsUiPlugin


def record(resumed=None, reason='进行股权分置改革的提示性公告'):
    return dict(market='SZ', code='000411', name='英特集团',
                suspended_at='2006-07-10T09:30:00', resumed_at=resumed,
                suspension_type='full_day', source_note='今起停牌', reason=reason)


def test_source_rows_remain_separate_and_unknown_resume_is_not_current_status():
    app = QApplication.instance() or QApplication([])
    requests = []
    def invoke(*args):
        future = Future()
        requests.append((args, future))
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={}, shutting_down=False)
    page = SuspensionsPage(shell)
    page.timer.stop()
    page.show()
    try:
        page.tick()
        old = requests[-1][1]
        old.set_running_or_notify_cancel()
        page.code.setText('000411')
        page.search()
        old.set_result([record(reason='旧查询')])
        current = requests[-1][1]
        current.set_result([record(), record('2006-07-31T09:30:00', '修改对价方案的沟通结果公告')])
        page.tick()
        assert page.table.rowCount() == 2
        assert page.table.item(0, 3).text() == '来源未提供'
        assert '09:30' in page.table.item(1, 3).text()
        page.table.selectRow(1)
        assert '修改对价方案' in page.detail.toPlainText()
        page.render([record()] * 51)
        assert page.next.isEnabled()
        page.move(1)
        assert requests[-1][0][-3] == 50
        page.calendar.setSelectedDate(QDate(2006, 7, 10))
        assert requests[-1][0][4:6] == ('2006-07-10', '2006-07-10')
        assert page.page == 0
        page.sort_column(3)
        assert requests[-1][0][-2:] == ('resumed_at', 'asc')
        page.sort_column(3)
        assert requests[-1][0][-2:] == ('resumed_at', 'desc')
        assert not page.table.isSortingEnabled()
        page.year.setValue(2012)
        page.month.setCurrentIndex(4)
        assert (page.calendar.yearShown(), page.calendar.monthShown()) == (2012, 5)
        page.all_dates.setChecked(True)
        assert requests[-1][0][4:6] == (None, None)
        page.calendar.clicked.emit(page.calendar.selectedDate())
        assert not page.all_dates.isChecked()
        assert requests[-1][0][4:6] == ('2006-07-10', '2006-07-10')
        page.all_dates.setChecked(True)
        page.code.setText('600113')
        state = page.save_ui_state()
        page.restore_ui_state(state)
        assert page.code.text() == '600113'
        assert page.direction == 'desc' and page.all_dates.isChecked()
        shell.shutting_down = True
        page.tick()
        assert page.query_scope.closed
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_suspension_page_is_catalogued_with_task_management():
    page, = SuspensionsUiPlugin().create_pages()
    assert page.catalogued and page.source == '通达信' and page.cache_policy == 'lru'
    assert page.management.context.task_id == 'tdx-suspensions'
