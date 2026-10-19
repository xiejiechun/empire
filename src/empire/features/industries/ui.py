"""Lazy current-industry browser; SQL belongs to the query plugin."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.data_browser.directory import DirectoryPanel
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    restore_table_identity,
    rows,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import compact_columns
from empire.plugins.ui.preview_navigation import navigate_security, security_context
from empire.plugins.ui.queries import QueryScope


class IndustryPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.offset, self.total = 0, 0
        self.selected_industry = ''
        self.applied_search, self.future, self.requested, self.dirty = '', None, None, False
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
        refresh.clicked.connect(lambda: self.directory.refresh())
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
        compact_columns(self.table, (85, 150, 55, 85, 120), 4)
        self.table.hideColumn(0)
        self.table.hideColumn(1)
        self.directory = DirectoryPanel(shell, 'industries.query', 'directory', 'industry_code',
            ('industry_code', 'name', 'member_count'), ['行业编号', '行业名称', '当前成员数'])
        self.directory.selected.connect(self.select_industry)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.directory)
        self.splitter.addWidget(self.table)
        self.splitter.setSizes([350, 700])
        self.table.itemDoubleClicked.connect(self.open_security)
        layout.addWidget(self.splitter, 1)
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
        self.applied_search, self.offset, self.dirty = self.search.text().strip(), 0, False
        self.directory.find(self.applied_search)

    def move(self, delta):
        self.offset = max(0, self.offset + delta)
        self.dirty = True

    def spec(self):
        return self.applied_search, self.offset, 200, self.selected_industry

    def select_industry(self, record):
        selected = record['industry_code'] if record else ''
        if selected != self.selected_industry:
            self.offset = 0
        self.selected_industry, self.dirty = selected, bool(record)
        if not record:
            rows(self.table, [])
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.status.setText('目录暂无匹配行业；未显示其他行业成员。')

    def open_security(self, *_):
        i = self.table.currentRow()
        if i >= 0:
            navigate_security(self.shell, 'listings', self.table.item(i, 3).text() + '.' + self.table.item(i, 2).text())

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.search.setText(code + '.' + market)
        self.find()

    def resizeEvent(self, event):
        self.splitter.setOrientation(Qt.Orientation.Vertical if self.width() < 800 else Qt.Orientation.Horizontal)
        super().resizeEvent(event)

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
                    self.status.setText(f"所选行业 {self.selected_industry} · {result['industry_count']} 个行业；匹配 {self.total} 个成员；"
                                        f"第 {self.offset // 200 + 1} 页，每页 200 条。"
                                        + ('' if result['publication'] else '尚未完整采集，请前往采集任务。'))
                    self.previous.setEnabled(self.offset > 0)
                    self.next.setEnabled(self.offset + 200 < self.total)
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('members', '查询失败', redact(exc, self.shell.cfg),
                                                                   stale=self.table.rowCount() > 0))
        if self.isVisible() and self.selected_industry and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('members', self.shell.runtime, 'industries.query', 'list_members',
                                            *self.requested)

    def save_ui_state(self):
        return dict(search=self.search.text(), applied=self.applied_search, offset=self.offset,
                    table=table_identity_state(self.table), directory=self.directory.save(), industry=self.selected_industry)

    def restore_ui_state(self, state):
        self.search.setText(state['search'])
        self.applied_search, self.offset, self.dirty = state['applied'], state['offset'], True
        restore_table_identity(self.table, state['table'])
        self.selected_industry = state.get('industry', '')
        if 'directory' in state:
            self.directory.restore(state['directory'])


class IndustryUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.industries', '当前行业界面', provides=('ui.pages.industries',),
                              description='按需创建的行业及成分浏览')

    def create_pages(self):
        return (PageContribution('industries', '同花顺当前行业', IndustryPage, '数据浏览', 10,
            '最新行业名单与成分股票，不保存变化历史', database_tables=('industry', 'industry_member'),
            catalogued=True, category='证券基础', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id='ths-industries'))),)
