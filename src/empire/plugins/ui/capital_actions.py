"""Independent lazy views for the three capital-action datasets."""
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.datasets.capital_actions import KINDS
from empire.plugins.ui.capital_words import LABELS
from empire.plugins.ui.common import accessible, bind_find, hint, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class CapitalPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind = shell, kind
        self.query_scope = QueryScope(self)
        self.page, self.records = 0, []
        self.future = self.requested = None
        self.dirty = True
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind][0])
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('通达信 · 已归档方案 · 每股金额/比例、股数；缺少的日期和数值保持未知'))
        layout.addWidget(hint('分红按除息日记账；增发/配股来源未提供公告时间，不用于公告前选股。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), '证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('证券代码（支持前缀）')
        self.code.setClearButtonEnabled(True)
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.search)
        bar.addWidget(self.code)
        refresh = QPushButton('查询 / 刷新')
        refresh.clicked.connect(self.search)
        bar.addWidget(refresh)
        manage = QPushButton('管理采集计划')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=KINDS[kind][2])))
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('正在查询……')
        layout.addWidget(self.status)
        self.table = table(['证券代码', '名称', '报告期 / 发行 / 除权日期', '方案进度 / 类型'])
        self.table.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(250)
        layout.addWidget(self.detail)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def spec(self):
        return (self.code.text().strip(), '', 51, self.page * 50)

    def search(self):
        self.page = 0
        self.reload()

    def move(self, step):
        self.page = max(0, self.page + step)
        self.reload()

    def reload(self):
        self.query_scope.cancel('events')
        self.future = None
        self.dirty = True
        self.tick()

    def render(self, result):
        self.records = result[:50]
        rows(self.table, [[r['code'], r['name'], r['event_date'] or '来源未提供',
                          r['data'].get('issue_method', r['data']['status'])] for r in self.records],
             keys=[r['record_key'] for r in self.records])
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(len(result) > 50)
        self.status.setText(f'第 {self.page + 1} 页 · {len(self.records)} 条；无记录不代表已完成采集')
        if self.records and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.show_detail()

    def show_detail(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.records):
            self.detail.clear()
            return
        r = self.records[index]
        values = {k: v for k, v in r['data'].items() if k != 'detail'}
        if self.kind == 'additional_issues':
            detail = r['data'].get('detail')
            if detail and detail.get('availability') == 'unavailable':
                values['详情状态'] = '来源暂无可用详情'
                values['来源接口状态'] = '返回空详情' if detail['source_error_code'] == 0 else '-1005（数据库执行失败）'
                if detail.get('last_available'):
                    values['历史参考说明'] = '以下保留上次有效明细，不代表来源本次提供的数据'
                    values.update(detail['last_available'])
            else:
                values.update(detail or {'详情采集': '尚未补齐，请继续采集'})
        self.detail.setPlainText(r['market'] + ' ' + r['code'] + ' ' + r['name'] + '\n' + '\n'.join(
            f"{LABELS.get(k, k)}：{v if v is not None else '来源未提供'}" for k, v in values.items()))

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.query_scope.discard('events', future)
            else:
                try:
                    self.render(self.query_scope.result('events', future))
                except Exception as exc:
                    self.status.setText(self.query_scope.failure_message('events', '查询失败',
                        redact(exc, self.shell.cfg), stale=bool(self.records)))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty = False
            self.requested = self.spec()
            self.future = self.query_scope.invoke('events', self.shell.runtime,
                self.kind + '.query', 'list_events', *self.requested)

    def save_ui_state(self):
        return {'code': self.code.text(), 'page': self.page}

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.page = state['page']
        self.dirty = True


class CapitalUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面',
            provides=('ui.pages.' + kind,), description='独立按需创建的通达信方案浏览')

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], partial(CapitalPage, kind=self.kind),
            '数据浏览', 4 + list(KINDS).index(self.kind), '通达信历史方案与证券关联',
            database_tables=(KINDS[self.kind][1],),
            catalogued=True, category='增发送配', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=KINDS[self.kind][2]))),)
