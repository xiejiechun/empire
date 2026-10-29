import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.identities import IdentityPage, IdentityUiPlugin  # noqa: E402


def snapshot():
    run = dict(id='prior', code='a', operation='login', status='failed',
               started_at='2026-10-24T01:00:00+00:00', finished_at='2026-10-24T01:01:00+00:00',
               error_code=-2, stage='passport', message='失败')
    return dict(platform='ths-yuanhang', running=True, total=1, offset=0, health={}, warning='',
                current=[dict(run, id='current', status='running')], last_run=run, unconfirmed=[],
                protocol_version='12.1.1.6', rows=[dict(code='a', profile_id='fixture', online=True,
                    registration='ready', creation=dict(provenance='legacy-reconstructed', imei='fixture-imei'),
                    last_run=run, current=[], unconfirmed=[])])


def test_lazy_page_platform_switch_cancels_read_and_commands_survive_disposal():
    app = QApplication.instance() or QApplication([])
    calls, commands = [], []
    futures = []

    def invoke(*args):
        calls.append(args)
        future = Future()
        futures.append(future)
        return future

    plugin = IdentityUiPlugin()
    assert plugin.create_pages()[0].id == 'identities' and not calls
    page = IdentityPage(SimpleNamespace(runtime=SimpleNamespace(invoke=invoke),
                                        command=lambda *args: commands.append(args)))
    page.timer.stop()
    assert not calls
    page.show()
    page.tick()
    futures[-1].set_result([dict(id='ths-yuanhang', name='同花顺远航版', plugin_id='source.yuanhang_identity'),
                           dict(id='other', name='另一平台', plugin_id='source.other')])
    page.tick()
    futures[-1].set_result(snapshot())
    page.tick()
    page.devices.setCurrentCell(0, 0)
    page.show_detail()
    assert '失败' in page.previous_round.text() and '当前1个操作' in page.previous_round.text()
    assert '旧版规则重建' in page.detail.toPlainText() and 'fixture-imei' in page.detail.toPlainText()
    assert page.pager.limit == calls[-1][-1] == 50
    page.pager.update_result(101, 0)
    page.pager.next.click()
    page.tick()
    assert calls[-1][3:] == (50, 50)
    futures[-1].set_result(snapshot())
    page.tick()
    page.render(snapshot())
    assert page.devices.currentRow() == 0
    page.command('stop')
    assert commands == [('stop', 'source.yuanhang_identity')]
    page.next_refresh = 0
    page.tick()
    pending = futures[-1]
    page.platform.setCurrentIndex(1)
    assert pending.cancelled() and page.devices.rowCount() == 0
    page.tick()
    assert calls[-1][2] == 'other'
    page.scope.close()
    assert futures[-1].cancelled() and commands
    page.close()
    page.deleteLater()
    app.processEvents()
