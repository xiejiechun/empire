import os
from concurrent.futures import Future
from datetime import date
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.yuanhang.ui import YuanhangPage, YuanhangUiPlugin  # noqa: E402


def test_lazy_query_applied_identity_pagination_and_draft_preservation():
    app = QApplication.instance() or QApplication([])
    calls = []
    def invoke(*args):
        f = Future()
        calls.append((args, f))
        return f
    shell = SimpleNamespace(cfg={}, runtime=SimpleNamespace(invoke=invoke), shutting_down=False)
    contribution = YuanhangUiPlugin().create_pages()[0]
    assert contribution.catalogued and contribution.cache_policy == 'lru' and not calls
    page = YuanhangPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        assert not calls
        page.find()
        page.tick()
        assert calls[-1][0][:4] == ('yuanhang.history.query', 'prices', '000001.SZ', '1900-01-01')
        page.code.setText('600519.SH')
        page.mode.setCurrentIndex(1)
        calls[-1][1].set_result(dict(rows=[dict(trade_date=date(2020,1,2), open='2',high='3',low='1',close='2',
                                              volume_shares='100', amount_yuan=None, quality_flags=1)],next='2020-01-02'))
        page.tick()
        assert page.code.text() == '600519.SH' and page.mode.currentIndex() == 1
        assert '000001.SZ' in page.status.text()
        assert page.table.item(0,6).text() == '未知'
        assert page.table.item(0,7).text() == 'OHLC异常'
        page.forward()
        page.tick()
        assert calls[-1][0][1:3] == ('prices','000001.SZ')
        assert calls[-1][0][-2] == '2020-01-02'
        page.find()
        calls[-1][1].set_result(dict(rows=[],next=None))
        page.tick()
        assert calls[-1][0][1:3] == ('actions','600519.SH')
    finally:
        shell.shutting_down=True
        page.tick()
        page.close()
        app.processEvents()
