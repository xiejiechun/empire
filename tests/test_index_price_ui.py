import os
from concurrent.futures import Future
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.index_prices import IndexPricePage, IndexPriceUiPlugin  # noqa: E402
from empire.plugins.ui.preparation_scope import PreparationScopeBar  # noqa: E402


def test_lazy_page_pagination_drafts_and_index_scope():
    app = QApplication.instance() or QApplication([])
    calls = []

    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future

    shell = SimpleNamespace(
        cfg={},
        runtime=SimpleNamespace(invoke=invoke),
        shutting_down=False,
        navigate_management=lambda _: None,
    )
    contribution = IndexPriceUiPlugin().create_pages()[0]
    assert contribution.catalogued and not calls
    page = IndexPricePage(shell)
    page.timer.stop()
    bar = PreparationScopeBar()
    try:
        page.show()
        app.processEvents()
        page.applied = ("399411", "", "")
        page.tick()
        page.code.setText("1A0001")
        sample = dict(
            index_code="399411",
            name="红利100",
            trade_date=date(2026, 10, 9),
            open=None,
            high=None,
            low=None,
            close=11,
            volume=100,
            amount=None,
            price_relation_valid=False,
        )
        calls[0][1].set_result(dict(rows=[sample], next=["2026-10-09", "399411"]))
        page.tick()
        assert page.code.text() == "1A0001" and page.table.item(0, 1).text() == "399411"
        assert page.table.item(0, 3).text() == "来源未提供"
        assert page.table.item(0, 8).text() == "来源未提供"
        assert page.table.item(0, 9).text() == "价格关系异常；来源缺少成交额"
        page.forward()
        page.tick()
        assert calls[-1][0][-2] == ["2026-10-09", "399411"]
        sample.update(amount=-798120910000, volume=-1)
        calls[-1][1].set_result(dict(rows=[sample], next=None))
        page.tick()
        assert page.table.item(0, 8).text() == "-798120910000"
        assert page.table.item(0, 9).text() == "价格关系异常；量额异常"
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.code.text() == "1A0001" and page.applied[0] == "399411"
        page.hide()
        before = len(calls)
        page.tick()
        assert len(calls) == before
        bar.index_codes.setText("1A0001,399411")
        assert bar.request()["index_codes"] == ["1A0001", "399411"]
        assert bar.request()["codes"] == []  # No hidden single-security default.
        state = bar.save()
        bar.restore(state)
        assert bar.index_codes.text() == "1A0001,399411"
    finally:
        page.close()
        page.deleteLater()
        bar.deleteLater()
        app.processEvents()
