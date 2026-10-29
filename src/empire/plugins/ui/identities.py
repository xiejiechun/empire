"""Lazy platform identity management; all reads are owned by QueryScope."""
import json
from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.common import Pager, hint, local_date, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope

STATES = {'unrequested': '待首次申请', 'requested': '申请已发起，未确认', 'rejected': '源站拒绝',
          'unknown': '申请结果未知', 'ready': '账号就绪'}
RESULTS = {'running': '进行中', 'success': '成功', 'failed': '失败', 'interrupted': '已取消',
           'unconfirmed': '未确认结束'}
OPERATIONS = {'application': '首次申请', 'login': '复用登录'}


def run_text(run):
    if not run:
        return '无保留记录'
    return (f"{OPERATIONS.get(run['operation'], run['operation'])} · "
            f"{RESULTS.get(run['status'], run['status'])} · "
            f"{local_date(run.get('finished_at') or run.get('started_at'))}"
            + (f" · 错误码 {run['error_code']}" if run.get('error_code') is not None else ''))


class IdentityPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.scope = QueryScope(self)
        self.future = self.spec = None
        self.offset, self.next_refresh = 0, 0
        self.platforms, self.data = {}, {}
        layout = QVBoxLayout(self)
        title = QLabel('身份管理')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('平台'))
        self.platform = QComboBox()
        self.platform.setAccessibleName('身份平台')
        self.platform.currentIndexChanged.connect(self.platform_changed)
        bar.addWidget(self.platform, 1)
        refresh = QPushButton('刷新')
        refresh.clicked.connect(self.reload)
        bar.addWidget(refresh)
        self.start_button, self.stop_button = QPushButton('启动自动身份服务'), QPushButton('停止自动身份服务')
        for button, action in ((self.start_button, 'start'), (self.stop_button, 'stop')):
            button.clicked.connect(lambda checked=False, action=action: self.command(action))
            button.setEnabled(False)
            bar.addWidget(button)
        layout.addLayout(bar)
        layout.addWidget(hint('按平台保存固定节点身份，code来自采集出口的设备列；离线档案保留。'
                              '查看和刷新不会申请账号或登录。启停只影响该平台身份服务。'))
        self.summary = hint('正在读取平台……')
        layout.addWidget(self.summary)
        self.previous_round = hint('上一已结束轮次：无保留记录')
        layout.addWidget(self.previous_round)
        self.devices = table(['节点 code', '目录', '身份状态', '上次已结束操作', '当前操作'])
        self.devices.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.devices.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.devices.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(self.devices, 2)
        self.pager = Pager(limit=50)
        self.pager.changed.connect(self.move)
        layout.addWidget(self.pager)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName('身份参数与上轮结果')
        self.detail.setPlaceholderText('选择节点查看首次申请参数、来源版本和上次结果。')
        layout.addWidget(self.detail, 1)
        layout.addWidget(hint('一轮指一次实际申请或登录；空闲扫描不覆盖上轮结果。每平台保留最近100条操作，'
                              'Redis或电脑重启后历史会丢失；身份配置仍保留。原始参数不代表当前协议仍受支持。'))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def command(self, action):
        platform = self.platforms.get(self.platform.currentData())
        if platform:
            # Shell owns mutations; page destruction must not cancel them.
            self.shell.command(action, platform['plugin_id'])
            self.next_refresh = 0

    def platform_changed(self):
        self.offset = 0
        self.data = {}
        self.devices.setRowCount(0)
        self.detail.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.reload()

    def move(self, offset):
        self.offset = offset
        self.reload()

    def reload(self):
        self.scope.cancel_all()
        self.future = self.spec = None
        self.next_refresh = 0

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, spec = self.future, self.spec
            self.future = self.spec = None
            try:
                data = self.scope.result('identities', future)
                if spec == 'catalog':
                    self.platforms = {p['id']: p for p in data}
                    self.platform.blockSignals(True)
                    for p in data:
                        self.platform.addItem(p['name'], p['id'])
                    self.platform.blockSignals(False)
                    self.next_refresh = 0
                else:
                    self.render(data)
            except Exception:
                self.summary.setText('身份信息读取失败；已有显示可能过期，请检查平台查询及数据库服务。')
        if not self.isVisible() or self.future or monotonic() < self.next_refresh:
            return
        self.next_refresh = monotonic() + 5
        self.spec = 'snapshot' if self.platforms else 'catalog'
        args = (self.platform.currentData(), self.offset, 50) if self.platforms else ()
        self.future = self.scope.invoke('identities', self.shell.runtime, 'identities.query', self.spec, *args)

    def render(self, data):
        self.data = data
        health = data['health']
        problems = '；'.join(filter(None, [data['warning'], health.get('error'), health.get('record_error')]))
        state = '已启动' if data['running'] else '已停止'
        if health.get('automatic_application_paused'):
            state += '，自动申请暂停'
        self.summary.setText(f"服务{state} · 保留{data['total']}个节点 · 当前登录协议{data['protocol_version']}"
                             + (f' · {problems}' if problems else ''))
        self.previous_round.setText('上一已结束轮次：' + run_text(data['last_run'])
            + f" · 当前{len(data['current'])}个操作"
            + (f" · {len(data['unconfirmed'])}个操作未确认结束" if data['unconfirmed'] else ''))
        rows(self.devices, [[r['code'], '在线' if r['online'] else '离线/未知', STATES[r['registration']],
             run_text(r['last_run']), '；'.join(run_text(v) for v in r['current'] + r['unconfirmed']) or '空闲']
             for r in data['rows']], keys=[r['code'] for r in data['rows']])
        self.pager.update_result(data['total'], data['offset'])
        self.start_button.setEnabled(not data['running'])
        self.stop_button.setEnabled(data['running'])
        self.show_detail()

    def show_detail(self):
        selected = self.devices.currentRow()
        if selected < 0 or selected >= len(self.data.get('rows', [])):
            self.detail.clear()
            return
        row = self.data['rows'][selected]
        creation = row['creation']
        provenance = '按旧版规则重建；真实首次申请时间未知' if creation['provenance'] == 'legacy-reconstructed' else '首次申请前保存'
        text = (f"节点：{row['code']}\n固定身份编号：{row['profile_id']}\n参数来源：{provenance}\n"
                f"申请状态：{STATES[row['registration']]} · 拒绝码：{row.get('rejection_code') if row.get('rejection_code') is not None else '无'}\n"
                f"上次结果：{run_text(row['last_run'])}\n"
                '固定延用：逻辑设备标识、IMEI；不使用本机物理MAC。账号与密码不展示。\n'
                '首次申请参数（只读）：\n' + json.dumps(creation, ensure_ascii=False, indent=2))
        if row['last_run']:
            text += '\n上轮诊断：\n' + json.dumps(row['last_run'], ensure_ascii=False, indent=2)
        if self.detail.toPlainText() != text:
            scroll = self.detail.verticalScrollBar().value()
            self.detail.setPlainText(text)
            self.detail.verticalScrollBar().setValue(scroll)


class IdentityUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.identities', '身份管理界面', provides=('ui.pages.identities',),
        description='平台身份、固定申请参数与上轮结果')

    def create_pages(self):
        return (PageContribution('identities', '身份管理', IdentityPage, '采集管理', 5,
                                  '按平台管理节点身份，查看申请参数及上次结果', cache_policy='lru'),)
