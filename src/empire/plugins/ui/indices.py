"""Lazy current-index catalogue and source-member browser."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
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
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    restore_table_identity,
    rows,
    table_identity_state,
)
from empire.plugins.ui.directory_panel import DirectoryPanel
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import compact_columns
from empire.plugins.ui.preview_navigation import navigate_security
from empire.plugins.ui.queries import QueryScope


class IndexPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_after, self.history = None, None, []
        self.future, self.requested, self.dirty = None, None, False
        self.applied_search = ''
        self.applied_mode = 'members'
        self.selected_index = ''
        self.index_record = None
        layout = QVBoxLayout(self)
        title = QLabel('同花顺当前指数及成分')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('只保存当前目录和成员。来源暂无时，已有成员仅作历史参考；不提供权重或历史调样。')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem('指数目录与成分', 'members')
        self.mode.addItem('证券反查所属指数', 'reverse')
        accessible(self.mode, '指数查询类型')
        self.mode.currentIndexChanged.connect(self.find)
        bar.addWidget(self.mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText('指数编号 / 指数名称 / 证券代码 / 证券名称')
        self.search.setMaxLength(100)
        accessible(self.search, '搜索当前指数及成分')
        bind_find(self, self.search)
        self.search.returnPressed.connect(self.find)
        bar.addWidget(self.search, 1)
        for text, action in [('查询', self.find), ('刷新', self.refresh),
                             ('前往采集任务', lambda: shell.navigate_management('indices'))]:
            button = QPushButton(text)
            button.clicked.connect(action)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.status = QLabel('正在读取已归档的当前指数…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        accessible(self.table, '当前指数及成分结果')
        compact_columns(self.table, (90, 140, 90, 115, 140, 105), 4)
        self.directory = DirectoryPanel(shell, 'indices.query', 'browse', 'index_code',
            ('index_code', 'index_name', 'source_group', 'member_count'),
            ['来源代码', '指数名称', '分组', '成员数'], prefix=('indices',))
        self.directory.selected.connect(self.select_index)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.directory)
        self.splitter.addWidget(self.table)
        self.splitter.setSizes([400, 700])
        self.table.itemDoubleClicked.connect(self.open_security)
        layout.addWidget(self.splitter, 1)
        self.view_prices = QPushButton('查看所选指数历史行情')
        self.view_prices.setEnabled(False)
        self.view_prices.clicked.connect(self.open_prices)
        layout.addWidget(self.view_prices)
        pagination = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(self.back)
        self.next.clicked.connect(self.forward)
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
        self.applied_search = self.search.text().strip()
        self.applied_mode = self.mode.currentData()
        self.view_prices.setEnabled(self.applied_mode != 'reverse' and bool(self.selected_index))
        self.directory.setVisible(self.applied_mode != 'reverse')
        if self.applied_mode != 'reverse':
            self.directory.find(self.applied_search)
        self.after, self.history, self.dirty = None, [], self.applied_mode == 'reverse'

    def forward(self):
        if self.next_after:
            self.history.append(self.after)
            self.after, self.dirty = self.next_after, True

    def refresh(self):
        if self.applied_mode == 'reverse':
            self.dirty = True
        else:
            self.directory.refresh()

    def back(self):
        if self.history:
            self.after, self.dirty = self.history.pop(), True

    def spec(self):
        return 'members', self.applied_search if self.applied_mode == 'reverse' else '', self.after, 200, self.selected_index if self.applied_mode != 'reverse' else ''

    def select_index(self, record):
        selected = record['index_code'] if record else ''
        if selected != self.selected_index:
            self.after, self.history = None, []
        self.selected_index = selected
        self.index_record = record
        self.view_prices.setEnabled(bool(record) and self.applied_mode != 'reverse')
        self.dirty = bool(record)
        if record:
            state = '待采集' if record['members_available'] is None else '当前成员' if record['members_available'] else '来源暂无，旧成员仅作历史参考'
            self.status.setText(record['index_name'] + ' · ' + state)
        else:
            rows(self.table, [])
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.status.setText('目录暂无匹配指数；未显示其他指数成员。')

    def open_prices(self):
        if self.selected_index and self.applied_mode != 'reverse':
            self.shell.navigate('index_prices', NavigationContext(index_code=self.selected_index, source='ths'))

    def open_security(self, *_):
        i = self.table.currentRow()
        if i >= 0 and (security := self.table.item(i, 3).text()) and '.' in security:
            navigate_security(self.shell, 'listings', security)

    def apply_navigation_context(self, context):
        if context.index_code:
            self.search.setText(context.index_code)
        elif context.unified_code:
            self.mode.setCurrentIndex(1)
            self.search.setText(context.unified_code)
        else:
            raise ValueError('指数目录导航缺少指数或证券身份')
        self.find()

    def resizeEvent(self, event):
        self.splitter.setOrientation(Qt.Orientation.Vertical if self.width() < 850 else Qt.Orientation.Horizontal)
        super().resizeEvent(event)

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('indices', future)
            else:
                try:
                    result = self.scope.result('indices', future)
                    directory = False
                    headers = (['指数编号', '指数名称', '来源分组', '成员数', '成员状态', '说明'] if directory
                               else ['指数编号', '指数名称', '来源证券代码', '统一证券代码', '证券名称', '成员状态'])
                    self.table.setHorizontalHeaderLabels(headers)
                    for column in (0, 1):
                        self.table.setColumnHidden(column, self.applied_mode != 'reverse')
                    values, keys = [], []
                    for row in result['rows']:
                        status = ('待采集' if row['members_available'] is None else
                                  '当前可用' if row['members_available'] else '来源暂无')
                        values.append([row['index_code'], row['index_name'], row['source_group'], row['member_count'],
                                       status, '网站分组' if row['members_available'] else '旧成员仅作历史参考'] if directory else
                                      [row['index_code'], row['index_name'], row['source_code'], row['unified_code'] or '未提供可确定市场',
                                       row['name'], status if row['members_available'] else '历史参考'])
                        keys.append((row['index_code'], '' if directory else row['source_code']))
                    rows(self.table, values, keys=keys)
                    self.next_after = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_after))
                    identity = (self.index_record['index_name'] + ' · ' + self.selected_index + ' · ' if self.index_record and self.applied_mode != 'reverse' else '证券反查 · ')
                    self.status.setText(identity + f'第{len(self.history) + 1}页，本页{len(values)}条；每页最多200条。'
                                        + ('' if values else '尚无匹配数据，可检查搜索条件或前往采集任务。'))
                    if self.index_record and self.applied_mode != 'reverse' and not self.index_record['members_available']:
                        self.status.setText(self.status.text() + ' 来源当前暂无成员；已有成员仅作历史参考。')
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('indices', '查询失败', redact(exc, self.shell.cfg),
                                                                   stale=self.table.rowCount() > 0))
        if self.isVisible() and (self.selected_index or self.applied_mode == 'reverse') and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('indices', self.shell.runtime, 'indices.query', 'browse', *self.requested)

    def save_ui_state(self):
        return dict(search=self.search.text(), applied=self.applied_search, mode=self.mode.currentIndex(),
                    after=self.after, history=self.history, table=table_identity_state(self.table),
                    directory=self.directory.save(), selected=self.selected_index, applied_mode=self.applied_mode)

    def restore_ui_state(self, state):
        self.mode.setCurrentIndex(state['mode'])
        self.search.setText(state['search'])
        self.applied_search, self.after, self.history = state['applied'], state['after'], state['history']
        restore_table_identity(self.table, state['table'])
        self.dirty = True
        self.selected_index = state.get('selected', '')
        self.applied_mode = state.get('applied_mode', 'members')
        if 'directory' in state:
            self.directory.restore(state['directory'])


class IndexUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.indices', '当前指数界面', provides=('ui.pages.indices',),
                              description='按需创建指数目录与成分浏览')

    def create_pages(self):
        return (PageContribution('indices', '同花顺当前指数及成分', IndexPage, '数据浏览', 11,
            '当前目录及成分；允许交叉归属，来源暂无单独标注', database_tables=('stock_index', 'stock_index_member'),
            catalogued=True, category='指数数据', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id='ths-indices'))),)
