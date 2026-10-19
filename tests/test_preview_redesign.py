"""Business counterexamples for the redesigned previews, not snapshot-only assertions."""
import os
from concurrent.futures import Future
from datetime import date
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.contracts.ui import NavigationContext  # noqa: E402
from empire.desktop.page_lifecycle import activate_page, deactivate_page  # noqa: E402
from empire.features.financial_statements.ui import StatementPage  # noqa: E402
from empire.features.index_prices.chart import IndexPriceChart  # noqa: E402
from empire.features.news.ui import NewsPage  # noqa: E402
from empire.features.suspensions.ui import SuspensionsPage
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS  # noqa: E402
from empire.plugins.ui.capital_preview import per_ten, plan_profile  # noqa: E402
from empire.plugins.ui.kaipanla_products import ProductPage  # noqa: E402
from empire.plugins.ui.month_grid import MonthGrid  # noqa: E402
from empire.plugins.ui.preview_cards import text  # noqa: E402
from empire.plugins.ui.series_chart import SeriesCanvas, clock_value, numeric  # noqa: E402
from tests.test_kaipanla_products import business_row  # noqa: E402
from tests.test_news_ui import result  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def shell():
    calls = []
    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future
    return SimpleNamespace(cfg={}, shutting_down=False, runtime=SimpleNamespace(invoke=invoke),
                           navigate_management=lambda _: None), calls


def dispose(page, app):
    page.close()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('kind', ['trend', 'volume', 'entrust', 'large_order'])
def test_whole_day_contains_afternoon_and_inspection_follows_original_point(app, kind):
    host, calls = shell()
    page = ProductPage(host, kind)
    page.timer.stop()
    try:
        page.show()
        page.code.setText('000001')
        page.find()
        page.tick()
        value = business_row(kind)
        assert len(value['data'][PRODUCTS[kind].field]) == 241
        calls[-1][1].set_result(dict(data=value, observed_at=None))
        page.tick()
        assert page.total == 241 and len(page.chart.canvases[0].points) == 241
        page.inspect_point(240)
        assert page.table.item(40, 0).text() == '241'
        assert page.points[-1][0] == '15:00'
        assert len(calls) == 1  # Detail page uses the finite day already loaded.
        page.table.selectRow(40)
        page.copy_selected()
        assert QApplication.clipboard().text().startswith('241\t15:00')
    finally:
        dispose(page, app)


def test_sequence_axis_keeps_same_minute_auction_without_inventing_seconds(app):
    canvas = SeriesCanvas('竞价', [(1, '来源价格')], sequence=True)
    points = business_row('auction')['data']['bid']
    canvas.set_series(points)
    assert canvas.domain() == list(range(5))
    assert len({r[0] for r in points}) < len(points)
    canvas.inspect(4)
    assert '来源序号 5' in canvas.accessibleDescription()
    canvas.deleteLater()


def test_real_time_domain_preserves_lunch_gap_and_null_zero(app):
    canvas = SeriesCanvas('量', [(1, '来源量')])
    canvas.set_series([['11:30', 0], ['13:00', None], ['13:01', 5]])
    assert canvas.domain()[1] - canvas.domain()[0] == 5400
    assert numeric(0) == 0 and numeric(None) is None and numeric('NaN') is None
    assert clock_value('13:01') == 46860
    canvas.deleteLater()


def test_month_weekend_unknown_is_not_closed_and_explicit_closed_remains(app):
    grid = MonthGrid()
    grid.render('2026-10', {'2026-10-02': ('休市', '来源确认', 'closed')})
    i = grid.days.index('2026-10-04')  # Sunday.
    assert '未知' in grid.buttons[i].text()
    grid.choose(i)
    assert '未取得该日证明' in grid.note.text()
    assert '休市' in grid.buttons[grid.days.index('2026-10-02')].text()
    grid.deleteLater()


def test_suspension_draft_and_pagination_keep_applied_source_day(app):
    host, _ = shell()
    page = SuspensionsPage(host)
    page.timer.stop()
    try:
        page.code.setText('000411')
        page.search()
        original = page.spec()
        page.code.setText('600519')
        page.page = 1
        assert page.spec()[:4] == original[:4]
        assert page.spec()[5] == 50
        page.records = [dict(code='000411', market='SZ', name='英特', suspended_at='2006-07-10',
                             resumed_at=None, source_note='来源说明', reason='原因')]
        page.render_cards()
        assert original[2] in page.cards.toPlainText()
        assert '不代表至今停牌' in page.cards.toPlainText()
    finally:
        dispose(page, app)


def test_news_notification_does_not_replace_reader_and_latest_returns_first_page(app):
    host, calls = shell()
    page = NewsPage(host)
    page.timer.stop()
    try:
        page.show()
        page.tick()
        calls[-1][1].set_result(result('<script>title</script>', total=120,
            next_cursor={'published_at': '2026-09-22T08:00:00', 'news_id': 0}))
        page.tick()
        before = page.feed.toPlainText()
        page.last_query = 0
        page.tick()
        assert calls[-1][0][1] == 'latest'
        calls[-1][1].set_result({'published_at': '2026-10-01T08:00:00', 'news_id': 100})
        page.tick()
        assert page.feed.toPlainText() == before and '有新消息' in page.update_button.text()
        assert '<script>' in before and '&lt;script&gt;' in text('<script>')
        page.page, page.cursors = 1, [None, {'published_at': '2026-09-22T08:00:00', 'news_id': 0}]
        page.show_latest()
        assert page.page == 0 and page.anchor is None
    finally:
        dispose(page, app)


def test_child_candidate_scope_cancelled_on_leave_then_reusable(app):
    host, calls = shell()
    page = ProductPage(host, 'trend')
    page.timer.stop()
    try:
        page.show()
        activate_page(page)
        page.candidates.search()
        future = calls[-1][1]
        assert page.candidates.future is future
        deactivate_page(page)
        assert future.cancelled() and page.candidates.future is None
        assert not page.candidates.poll.isActive()
        activate_page(page)
        assert page.candidates.poll.isActive()
    finally:
        dispose(page, app)


def test_anomalous_ohlc_is_gap_but_valid_close_remains_available(app):
    chart = IndexPriceChart()
    raw = dict(trade_date=date(2026, 10, 9), open=12, high=11, low=9, close=10,
               price_relation_valid=False, volume=0, amount=None, volume_amount_valid=True)
    chart.set_result(dict(index_code='399411', start='2026-10-01', end='2026-10-09', rows=[raw]))
    assert chart.canvas.points[0]['close'] is None
    assert chart.close_chart.canvases[0].points[0][1] == 10
    assert chart.amounts.canvases[0].points[0][1] == 0
    assert chart.amounts.canvases[1].points[0][2] is None
    chart.deleteLater()


def test_source_snapshot_warning_and_exact_ten_share_decimal():
    assert per_ten('0.123456789') == '1.234567890'
    assert per_ten(0) == '0' and per_ten(None) == '未知'
    profile = plan_profile('additional_issues', dict(name='公司', code='600000', market='SH',
        data={'status': '完成', 'detail': {'availability': 'unavailable', 'last_available': {'issue_price': 2}}}))
    assert '历史参考' in profile and '来源本次暂无可用详情' in profile


def test_statement_candidate_preserves_market_and_balance_has_point_in_time_label(app):
    host, _ = shell()
    page = StatementPage(host, 'balance')
    page.timer.stop()
    try:
        page.candidates.options['000001.SH 样本'] = dict(unified_code='000001.SH', name='样本')
        page.candidates.choose('000001.SH 样本')
        assert page.selected == ('SH', '000001')
        assert '时点' in page.views.tabText(1)
        with pytest.raises(ValueError):
            NavigationContext(unified_code='000001.SZ', index_code='1A0001', source='ths')
    finally:
        dispose(page, app)
