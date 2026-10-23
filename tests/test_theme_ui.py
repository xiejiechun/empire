import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.themes.ui import ThemePage, ThemeUiPlugin  # noqa: E402


def test_page_is_lazy_preserves_drafts_cancels_reads_and_uses_parent_detail():
    app = QApplication.instance() or QApplication([])
    calls = []
    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(config={}, invoke=invoke), navigate=lambda *a: None)
    declaration = ThemeUiPlugin().create_pages()[0]
    assert declaration.id == 'themes' and not calls
    page = declaration.factory(shell)
    assert not calls
    row = dict(theme_id='148_1', source_theme_id='148', name='子题材', parent_id='148',
               display_order=0, rank_no=None, hot_score=None, change_rate='1.25', limit_up_count=0)
    page.present({'rows': [row], 'at': '2026-10-24T01:00:00+00:00'})
    assert '来源未提供' in page.reader.toPlainText()
    page.choose_detail(0)
    assert page.theme.text() == '148' and page.applied[0] == 3
    page.day.setText('2026-10-22')
    state = page.save_ui_state()
    other = ThemePage(shell)
    other.restore_ui_state(state)
    assert other.day.text() == '2026-10-22' and other.applied == page.applied
    page.show()
    app.processEvents()
    page.tick()
    assert calls and calls[-1][0][1] == 'detail_page'
    page.hide()
    assert calls[-1][1].cancelled()
    page.close()
    other.close()
