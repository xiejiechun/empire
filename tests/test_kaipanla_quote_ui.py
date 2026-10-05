"""Business-facing quote layout and optional-query isolation regressions."""
import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.kaipanla_products import KaipanlaProductUiPlugin  # noqa: E402
from empire.plugins.ui.kaipanla_quote_format import GREEN  # noqa: E402
from empire.plugins.ui.kaipanla_quote_page import QuotePage  # noqa: E402
from tests.test_kaipanla_products import business_row  # noqa: E402


def test_quote_book_order_missing_related_trend_and_query_identity():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
                            navigate_management=lambda _: None, shutting_down=False)
    page = KaipanlaProductUiPlugin('quote').create_pages()[0].factory(shell)
    assert isinstance(page, QuotePage) and not pending
    page.timer.stop()
    try:
        page.resize(1100, 900)
        page.show()
        app.processEvents()
        page.day.setDate(QDate(2021, 1, 4))
        page.find()
        page.tick()
        assert pending[0][0][:2] == ('kaipanla_quote.query', 'day')
        value = business_row('quote')
        value['data']['preclose_px'] = 10.5
        value['data']['name'] = '测试证券'
        value['data']['real']['px_change'] = -.5
        value['data']['real']['px_change_rate'] = -4.76
        page.code.setText('600519')  # Draft must not relabel the accepted quote.
        pending[0][1].set_result(dict(data=value, observed_at=None))
        page.tick()
        assert '000001.SZ' in page.view.identity.text()
        assert page.code.text() == '600519'
        assert page.view.price.text() == '10.00'
        assert GREEN in page.view.price.styleSheet()
        assert page.view.book.rowCount() == 10
        assert [page.view.book.item(i, 0).text() for i in (0, 4, 5, 9)] == ['卖5', '卖1', '买1', '买5']
        assert page.view.book.item(4, 1).foreground().color().name() == GREEN
        assert pending[1][0] == ('kaipanla_trend.query', 'day', 'SZ', '000001', '2021-01-04')
        pending[1][1].set_result(None)
        page.tick()
        assert not page.view.chart.points and '尚无' in page.view.chart.message
        assert page.view.price.text() == '10.00'
        page.view.depth.setCurrentIndex(1)
        assert page.view.book.rowCount() == 20
        assert page.view.book.item(0, 0).text() == '卖10'
        assert page.view.book.item(10, 0).text() == '买1'
        assert page.save_ui_state()['depth'] == 1
        page.find()
        page.tick()
        pending[-1][1].set_result(None)
        page.tick()
        assert page.view.price.text() == '—'
        assert page.view.book.item(0, 1).text() == '—'
        assert len(pending) == 3  # No extra queries or collectors when quote is absent.
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_late_related_query_cannot_mix_securities():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append(future)
        return future
    page = QuotePage(SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke),
        navigate_management=lambda _: None, shutting_down=False), 'quote')
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.find()
        page.tick()
        pending[0].set_result(dict(data=business_row('quote'), observed_at=None))
        page.tick()
        page.code.setText('600519')
        page.find()
        pending[1].set_result(dict(data=business_row('trend'), observed_at=None))
        page.tick()
        assert not page.view.chart.points
        pending[2].set_result(dict(data=business_row('quote'), observed_at=None))
        page.tick()
        pending[3].set_exception(RuntimeError('trend plugin disabled'))
        page.tick()
        assert '不可用' in page.view.chart.message
        assert page.view.price.text() == '10.00'
        page.find()
        page.tick()
        pending[4].set_exception(RuntimeError('SQL temporarily unavailable'))
        page.tick()
        assert '旧数据' in page.status.text()
        assert page.view.price.text() == '10.00'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
