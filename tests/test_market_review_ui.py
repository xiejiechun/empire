import os
from concurrent.futures import Future
from datetime import date
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.market_review.model import summarize  # noqa: E402
from empire.features.market_review.ui import ReviewPage, ReviewUi  # noqa: E402


def test_lazy_page_discards_stale_response_preserves_draft_and_clears_failures():
    app = QApplication.instance() or QApplication([])
    calls = []
    def invoke(*args):
        f = Future()
        calls.append((args, f))
        return f
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke), shutting_down=False)
    contribution = ReviewUi().create_pages()[0]
    assert contribution.top_level and not contribution.catalogued
    assert contribution.group == '市场复盘'
    page = ReviewPage(shell)
    page.timer.stop()
    page.show()
    app.processEvents()
    try:
        page.tick()
        assert calls == []
        page.apply_filters()
        page.tick()
        page.start.setText('2026-10-01')
        day = date(2026, 10, 26)
        data = summarize([day], [], [], [], day)
        data['queried_at'] = '2026-10-28 00:00:00'
        calls[-1][1].set_result(data)
        page.tick()
        assert page.start.text() == '2026-10-01'
        assert page.cards['up'].text().endswith('—')
        page.apply_filters()
        page.tick()
        page.end.setText('2026-10-20')
        page.apply_filters()
        calls[-1][1].set_result(data)
        page.tick()
        assert calls[-1][0][-1] == '2026-10-20'
        calls[-1][1].set_exception(ValueError('日历缺日'))
        page.tick()
        assert page.tables['full'].rowCount() == 0 and '缺日' in page.status.text()
    finally:
        shell.shutting_down = True
        page.tick()
        page.close()
        app.processEvents()
