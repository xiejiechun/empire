import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.contracts.ui import NavigationContext  # noqa: E402
from empire.features.yuanhang_limits.ui import LimitsPage, LimitsUiPlugin  # noqa: E402


def test_volatile_completion_does_not_claim_mysql_confirmation():
    from empire.plugins.collection.progress import display_snapshot
    from empire.plugins.ui.collection_views.task_runtime import archive_label
    saved = display_snapshot(dict(storage='redis_only', collected=5))
    assert archive_label('complete', saved) == 'Redis快照已保存；未归档MySQL'
    assert archive_label('complete', dict(storage='none')) == '本轮无需采样，没有新增归档'
    assert archive_label('complete', {}) == '整轮已确认，可查询'


def test_source_zero_time_displays_unknown_without_claiming_epoch_event():
    from datetime import datetime

    from empire.core.time import CHINA
    from empire.features.yuanhang_limits.ui import display_value
    assert display_value('first_limit_up_time', datetime.fromtimestamp(0, CHINA).replace(tzinfo=None)) == '未知（来源0）'
    assert display_value('first_limit_up_time', None) == '未知'


def test_lazy_page_preserves_draft_and_applied_pagination_and_navigation():
    app = QApplication.instance() or QApplication([])
    calls = []

    def invoke(*args):
        result = Future()
        calls.append((args, result))
        return result

    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke), shutting_down=False)
    contribution = LimitsUiPlugin().create_pages()[0]
    assert contribution.catalogued and contribution.cache_policy == 'lru' and not calls
    page = LimitsPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        assert not calls
        page.apply_filters()
        page.tick()
        applied = calls[-1][0][2]
        page.code.setText('600519.SH')
        page.mode.setCurrentIndex(2)
        calls[-1][1].set_result(dict(rows=[dict(unified_code='000001.SZ', pool_type='limit_up_pool', latest=None)],
                                   next='000001.SZ', message='来源池'))
        page.tick()
        assert page.code.text() == '600519.SH' and page.mode.currentIndex() == 2
        assert page.table.item(0, 4).text() == '未知'
        page.forward()
        page.tick()
        assert calls[-1][0][2] == applied and calls[-1][0][3] == '000001.SZ'
        page.apply_navigation_context(NavigationContext(unified_code='000002.SZ', start='2020-01-01', end='2026-07-15'))
        calls[-1][1].set_result(dict(rows=[], next=None, message='stale'))
        page.tick()
        assert calls[-1][0][2] == (1, 'limit_up_pool', '000002.SZ', '2020-01-01', '2026-07-15', '')
        assert page.status.text() != 'stale'
    finally:
        shell.shutting_down = True
        page.tick()
        page.close()
        app.processEvents()
