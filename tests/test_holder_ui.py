import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.contracts.holders import report_key  # noqa: E402
from empire.plugins.collectors.ths_holders_source import parse  # noqa: E402
from empire.plugins.ui.holders import HolderPage, HolderUiPlugin  # noqa: E402
from tests.test_ths_holders import STOCK, source  # noqa: E402


def test_source_quality_and_unknowns_are_visible_without_overwriting_values():
    from tests.test_holder_quality import quality_source
    app = QApplication.instance() or QApplication([])
    page = HolderPage(SimpleNamespace(), 'top_holders')
    page.timer.stop()
    try:
        row = parse(quality_source('top_holders', 'quantity_mismatch'), 'top_holders', STOCK)[0]
        page.render(row)
        text = page.reader.toPlainText()
        assert '来源质量异常' in text and '来源当期列示名单' in text
        assert '200.00万股' in text and '1000000' in text and '100000' in text
        row = parse(quality_source('top_holders', 'missing_ratio'), 'top_holders', STOCK)[0]
        page.render(row)
        assert '10位当期持有人比例未知' in page.reader.toPlainText()
        assert '未知（来源未提供）' in page.reader.toPlainText()
        row = parse(quality_source('top_holders', 'missing_quantity_summary'), 'top_holders', STOCK)[0]
        page.render(row)
        assert '来源数量汇总未知' in page.reader.toPlainText() and 'None' not in page.reader.toPlainText()
        for shape, text in [('missing_quantity', '当期持有数量未知'), ('missing_exit_quantity', '退出持有数量未知'), ('future_date', '来源报告期晚于采集观察日')]:
            page.render(parse(quality_source('top_holders', shape), 'top_holders', STOCK)[0])
            assert text in page.reader.toPlainText() and 'None' not in page.reader.toPlainText()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_lazy_report_selection_drafts_and_hidden_reads():
    app = QApplication.instance() or QApplication([])
    pending = []
    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke, config={}))
    spec = HolderUiPlugin('top_holders').create_pages()[0]
    assert spec.catalogued and spec.management.context.task_id == 'ths-holders'
    page = HolderPage(shell, 'top_holders')
    page.timer.stop()
    report = parse(source(), 'top_holders', STOCK)[0]
    key = report_key(report)
    try:
        page.show()
        app.processEvents()
        page.tick()
        page.code.setText('草稿保留')
        pending[-1][1].set_result(dict(rows=[{**report, 'report_key': key}], next=None))
        page.tick()
        assert page.code.text() == '草稿保留' and pending[-1][0][-2:] == ('detail', key)
        pending[-1][1].set_result(report)
        page.tick()
        assert '100.00万股' in page.reader.toPlainText() and '较上期退出' in page.reader.toPlainText()
        saved = page.save_ui_state()
        page.restore_ui_state(saved)
        assert page.code.text() == '草稿保留'
        page.hide()
        size = len(pending)
        page.tick()
        assert len(pending) == size and not page.timer.isActive()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
