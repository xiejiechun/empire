"""Lazy current-industry browser; SQL belongs to the query plugin."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    restore_table_identity,
    rows,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class IndustryPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.offset, self.total = 0, 0
        self.applied_search, self.future, self.requested, self.dirty = '', None, None, True
        layout = QVBoxLayout(self)
        title = QLabel('同花顺当前行业')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('行业名单及成分股票只保留最新一份；不提供历史归属或变更记录。')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('行业名称 / 行业编号 / 证券代码 / 证券名称')
        self.search.setMaxLength(100)
        accessible(self.search, '搜索当前行业及股票')
        bind_find(self, self.search)
        self.search.returnPressed.connect(self.find)
        bar.addWidget(self.search, 1)
        find = QPushButton('查询')
        find.clicked.connect(self.find)
        bar.addWidget(find)
        refresh = QPushButton('刷新')
        refresh.clicked.connect(lambda: setattr(self, 'dirty', True))
        bar.addWidget(refresh)
        collect = QPushButton('前往采集任务')
        collect.clicked.connect(lambda: shell.navigate_management('industries'))
        bar.addWidget(collect)
        layout.addLayout(bar)
        self.status = QLabel('正在读取已归档的当前行业…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['行业编号', '行业名称', '市场', '证券代码', '证券名称'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        accessible(self.table, '当前行业成分结果')
        layout.addWidget(self.table, 1)
        pagination = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(-200))
        self.next.clicked.connect(lambda: self.move(200))
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        pagination.addStretch()
        layout.addLayout(pagination)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def find(self):
        self.applied_search, self.offset, self.dirty = self.search.text().strip(), 0, True

    def move(self, delta):
        self.offset = max(0, self.offset + delta)
        self.dirty = True

    def spec(self):
        return self.applied_search, self.offset, 200

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('members', future)
            else:
                try:
                    result = self.scope.result('members', future)
                    rows(self.table, [[r[k] for k in ('industry_code', 'industry_name', 'market', 'code', 'name')]
                                      for r in result['rows']],
                         keys=[(r['industry_code'], r['market'], r['code']) for r in result['rows']])
                    self.total = result['total']
                    self.status.setText(f"{result['industry_count']} 个行业；匹配 {self.total} 个成员；"
                                        f"第 {self.offset // 200 + 1} 页，每页 200 条。"
                                        + ('' if result['publication'] else '尚未完整采集，请前往采集任务。'))
                    self.previous.setEnabled(self.offset > 0)
                    self.next.setEnabled(self.offset + 200 < self.total)
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('members', '查询失败', redact(exc, self.shell.cfg),
                                                                   stale=self.table.rowCount() > 0))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('members', self.shell.runtime, 'industries.query', 'list_members',
                                            *self.requested)

    def save_ui_state(self):
        return dict(search=self.search.text(), applied=self.applied_search, offset=self.offset,
                    table=table_identity_state(self.table))

    def restore_ui_state(self, state):
        self.search.setText(state['search'])
        self.applied_search, self.offset, self.dirty = state['applied'], state['offset'], True
        restore_table_identity(self.table, state['table'])


class IndustryUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.industries', '当前行业界面', provides=('ui.pages.industries',),
                              description='按需创建的行业及成分浏览')

    def create_pages(self):
        return (PageContribution('industries', '同花顺当前行业', IndustryPage, '数据浏览', 10,
            '最新行业名单与成分股票，不保存变化历史', database_tables=('industry', 'industry_member'),
            catalogued=True, category='证券基础', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id='ths-industries'))),)
