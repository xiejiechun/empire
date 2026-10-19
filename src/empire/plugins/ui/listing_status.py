"""Lazy event browser: bounded cursor pages and separately fetched source text."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.listing_status import COLUMNS, PROJECT, TYPES
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.data_browser.search import CandidateSearch
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    hint,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, text
from empire.plugins.ui.preview_layout import QueryForm
from empire.plugins.ui.preview_navigation import security_context
from empire.plugins.ui.queries import QueryScope


class ListingStatusPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.applied, self.future, self.detail_future = ('', '', '', ''), None, None
        self.requested, self.detail_key, self.records = None, None, []
        self.dirty = True
        layout = QVBoxLayout(self)
        title = QLabel('暂停恢复终止上市（通达信）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('按来源日期保存暂停、恢复、终止上市；暂停不是退市。简称不代表历史当日名称；不提供最后交易日或完整重新上市历史。'))
        self.code = accessible(QLineEdit(), '上市状态证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('证券代码或前缀')
        bind_find(self, self.code)
        self.kind = accessible(QComboBox(), '上市状态事件类型')
        self.kind.addItem('全部事件', '')
        for key, label in TYPES.items():
            self.kind.addItem(label, key)
        self.start, self.end = QLineEdit(), QLineEdit()
        for box, label in ((self.start, '开始日期'), (self.end, '结束日期')):
            accessible(box, '上市状态' + label)
            box.setPlaceholderText(label + ' YYYY-MM-DD')
            box.setMaxLength(10)
            box.returnPressed.connect(self.find)
        self.code.returnPressed.connect(self.find)
        self.candidates = CandidateSearch(self, self.code, shell, 'listing_status',
            lambda r: self.code.setText(r['unified_code']))
        find = QPushButton('查询 / 刷新')
        find.clicked.connect(self.find)
        manage = QPushButton('管理采集任务')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=PROJECT)))
        layout.addWidget(QueryForm([('证券名称 / 代码', self.code), ('事件类型', self.kind),
            ('开始日期', self.start), ('截止日期', self.end)], [find, manage]))
        self.status = hint('正在读取已归档事件…')
        layout.addWidget(self.status)
        self.table = table(['来源日期', '证券', '事件', '来源简称'])
        self.table.itemSelectionChanged.connect(self.selected)
        self.views = QTabWidget()
        self.timeline = CardReader('上市状态来源事件时间线')
        self.timeline.selected.connect(self.open_description)
        self.views.addTab(self.timeline, '事件时间线')
        self.views.addTab(self.table, '来源明细')
        layout.addWidget(self.views, 1)
        self.description = hint('选择事件查看来源说明；空说明表示来源未提供。')
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.description_view = QScrollArea()
        self.description_view.setWidgetResizable(True)
        self.description_view.setWidget(self.description)
        self.views.addTab(self.description_view, '所选事件说明')
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def find(self):
        self.applied = (self.code.text().strip(), self.kind.currentData(), self.start.text().strip(), self.end.text().strip())
        self.after, self.next_cursor, self.history = None, None, []
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.dirty = True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def spec(self):
        return (*self.applied, self.after, 200, True)

    def apply_navigation_context(self, context):
        security_context(context)
        self.code.setText(context.unified_code)
        self.start.setText(context.start)
        self.end.setText(context.end)
        self.find()

    def render_timeline(self):
        self.timeline.present(''.join(card(TYPES[r['event_type']],
            f'<p>{text(r["unified_code"])} · {text(r["name"])}（来源简称）</p>'
            + f'<p><a href="record:{i}">查看来源说明</a></p>', r['event_date'] + ' · 来源日期')
            for i, r in enumerate(self.records)) or '<p>暂无匹配的已归档事件。</p>',
            identity=(self.applied, self.after))

    def selected(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.records):
            self.scope.cancel('detail')
            self.detail_future = None
            self.description.setText('当前没有所选事件；先选择一条记录。')
            return
        if not self.isVisible():
            return
        key = [self.records[index][k] for k in COLUMNS[:4]]
        if self.detail_future:
            self.scope.cancel('detail')
        self.detail_key = key
        self.description.setText('正在读取来源说明…')
        self.detail_future = self.scope.invoke('detail', self.shell.runtime, 'listing_status.query', 'detail', key)

    def open_description(self, index):
        self.table.selectRow(index)
        self.selected()
        self.views.setCurrentWidget(self.description_view)

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            try:
                result = self.scope.result('detail', future)
                self.description.setText(('事件已更新或删除，请刷新列表。' if not result['found'] else
                    result['description'] if result['description'] is not None else '来源未提供说明。'))
            except Exception as exc:
                self.description.setText('说明查询失败：' + redact(exc, self.shell.cfg))
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('events', future)
            else:
                try:
                    result = self.scope.result('events', future)
                    self.records = result['rows']
                    self.render_timeline()
                    self.table.blockSignals(True)
                    rows(self.table, [[r['event_date'], r['unified_code'], TYPES[r['event_type']], r['name']] for r in self.records],
                         keys=[r['record_key'] for r in self.records])
                    self.table.blockSignals(False)
                    if self.records and self.table.currentRow() < 0:
                        self.table.selectRow(0)
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'第{len(self.history) + 1}页；本页{len(self.records)}条；每页最多200条。')
                    self.selected()
                except Exception as exc:
                    self.table.blockSignals(False)
                    self.status.setText(self.scope.failure_message('events', '查询失败', redact(exc, self.shell.cfg), stale=self.table.rowCount() > 0))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('events', self.shell.runtime, 'listing_status.query', 'list_events', *self.requested)

    def save_ui_state(self):
        return dict(code=self.code.text(), kind=self.kind.currentIndex(), start=self.start.text(), end=self.end.text(),
                    applied=self.applied, after=self.after, history=list(self.history), table=table_identity_state(self.table),
                    view=self.views.currentIndex(), position=self.timeline.save_position())

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.kind.setCurrentIndex(state['kind'])
        self.start.setText(state['start'])
        self.end.setText(state['end'])
        self.applied, self.after, self.history = state['applied'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True
        self.views.setCurrentIndex(state.get('view', 0))
        self.timeline.restore_position(state.get('position', 0))


class ListingStatusUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.listing_status', '暂停恢复终止上市界面', provides=('ui.pages.listing_status',),
                              description='独立按需创建事件浏览页')

    def create_pages(self):
        return (PageContribution('listing_status', '暂停恢复终止上市', ListingStatusPage, '数据浏览', 20,
            '沪深A股来源事件、日期及说明', database_tables=('security_listing_event',),
            catalogued=True, category='证券基础', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
