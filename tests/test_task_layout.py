"""Check the real shell geometry rather than scrolling clipped controls into view."""
import threading

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from test_collection_ui import Runtime as ActionRuntime
from test_collection_ui import snapshot

from empire.desktop.window import MainWindow
from empire.plugins.ui.collection import CollectionUiPlugin


class Runtime(ActionRuntime):
    def __init__(self):
        super().__init__()
        self.closed = threading.Event()

    def page_contributions(self):
        return CollectionUiPlugin().create_pages()

    def snapshot(self):
        return {'plugins': []}


@pytest.fixture
def task_window():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Runtime(), {})
    window.timer.stop()
    window.navigate('collection')
    page = window.page_widgets['collection']
    page.timer.stop()
    page.data = snapshot()
    page.data.update(total=1, offset=0)
    page.data['jobs'][0].update(name='新浪 7×24 小时全球实时财经新闻直播',
                              description='最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻')
    page.render()
    yield window, page, app
    window.can_close = True
    window.close()
    window.deleteLater()
    app.processEvents()


def settle(app):
    app.processEvents()
    app.processEvents()


def test_plugin_defaults_keep_schedule_controls_editable_and_preserve_drafts(task_window):
    from empire.plugins.collection.task_defaults import HISTORICAL_DAY_DEFAULTS
    window, page, app = task_window
    job = page.data['jobs'][0]
    job['default_schedule'] = HISTORICAL_DAY_DEFAULTS.description
    job['policy'] = HISTORICAL_DAY_DEFAULTS.policy(job['policy'])
    page.render()
    window.show()
    page.task_inspector.setCurrentIndex(1)
    settle(app)
    assert not page.mode.isHidden() and not page.daily.isHidden()
    assert page.interval.isHidden()
    assert HISTORICAL_DAY_DEFAULTS.description in page.plan_note.text()
    baseline = page._policy()
    page.mode.setCurrentIndex(page.mode.findData('interval'))
    page.interval.setValue(123)
    assert not page.interval.isHidden() and page.daily.isHidden()
    draft = page._policy()
    page.render()
    assert page._policy() == draft and page.loaded_id in page.job_drafts
    page.reset_job()
    assert page._policy() == baseline
    page.mode.setCurrentIndex(page.mode.findData('manual'))
    assert not page.mode.isHidden() and page.daily.isHidden() and page.interval.isHidden()


def in_view(widget, area):
    point = widget.mapTo(area.viewport(), QPoint(0, 0))
    return (point.x() >= 0 and point.y() >= 0
            and point.x() + widget.width() <= area.viewport().width()
            and point.y() + widget.height() <= area.viewport().height())


@pytest.mark.parametrize('width,height', [(1320, 860), (1320, 700)])
def test_normal_window_keeps_menu_actions_and_save_in_view(task_window, width, height):
    window, page, app = task_window
    window.resize(width, height)
    window.show()
    settle(app)
    area = window.page_containers['collection']
    for index in (0, 1, 0, 1):
        page.task_inspector.setCurrentIndex(index)
        page.interval.setValue(45)
        settle(app)
        assert window.size().width() == width and window.size().height() == height
        assert area.horizontalScrollBar().maximum() == 0
        assert area.verticalScrollBar().maximum() == 0
        assert in_view(page.task_menu, area)
        for button in (page.run_button, page.pause_button, page.fresh_button, page.archive_button):
            assert in_view(button, area)
        assert page.run_button.mapTo(page, QPoint()).y() == page.pause_button.mapTo(page, QPoint()).y()
        assert page.fresh_button.mapTo(page, QPoint()).y() == page.archive_button.mapTo(page, QPoint()).y()
        assert page.fresh_button.mapTo(page, QPoint()).y() > page.run_button.mapTo(page, QPoint()).y()
        if index == 1:
            assert in_view(page.save_panel, area)
            assert page.save_button.isEnabled()
    assert 280 <= page.task_menu.width() <= 340


def test_long_error_scrolls_inside_details_and_does_not_move_page(task_window):
    window, page, app = task_window
    error = '请求失败：包含需要完整保留的错误内容。\n' * 100
    page.data['jobs'][0].update(last_status='error', error=error)
    page.render()
    window.resize(1320, 700)
    window.show()
    settle(app)
    area = window.page_containers['collection']
    inner = page.task_inspector.widget(0)
    assert area.verticalScrollBar().maximum() == 0
    assert inner.verticalScrollBar().maximum() > 0
    inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum())
    settle(app)
    assert in_view(page.run_button, area)
    assert in_view(page.task_menu, area)
    assert page.runtime_fields['error'].text() == error
    page.data['jobs'][0]['error'] = ''
    page.render()
    settle(app)
    assert area.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize('width', [1024, 880, 680])
def test_narrow_window_wraps_without_forcing_horizontal_overflow(task_window, width):
    window, page, app = task_window
    window.resize(width, 560)
    window.show()
    page.task_inspector.setCurrentIndex(1)
    page.interval.setValue(73)
    settle(app)
    area = window.page_containers['collection']
    assert window.width() == width
    assert area.horizontalScrollBar().maximum() == 0
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    settle(app)
    assert in_view(page.save_panel, area)
    assert page.interval.value() == 73
    assert page.task_split.orientation() == Qt.Orientation.Vertical


def test_source_selection_has_only_an_empty_prompt_and_no_stale_statistics(task_window):
    window, page, app = task_window
    window.resize(1320, 700)
    window.show()
    settle(app)
    page.task_menu.setCurrentItem(page.task_menu.group_items['sina'])
    settle(app)
    assert page.detail_stack.currentIndex() == 0
    assert not page.task_inspector.isVisible()
    assert not page.run_button.isVisible()
    assert not page.save_panel.isVisible()
    page.task_menu.select_task('stocks')
    settle(app)
    assert page.detail_stack.currentIndex() == 1
    assert page.task_inspector.isVisible()
