"""Lazy cursor-paged browsers for two distinct ST categories."""
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.st_events import KINDS, project
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    hint,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.event_timeline import EventTimeline
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_navigation import security_context
from empire.plugins.ui.preview_search import CandidateSearch
from empire.plugins.ui.queries import QueryScope


class StPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.future = self.requested = None
        self.applied, self.dirty = '', True
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind][0] + '（通达信）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('来源实施或撤销日期、前后简称及原因；栏目含风险警示类型转换，不能仅据本表推断每日ST状态。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), 'ST事件证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('六位证券代码或前缀')
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.find)
        self.candidates = CandidateSearch(self, self.code, shell, 'st_' + kind,
            lambda r: self.code.setText(r['unified_code']))
        bar.addWidget(self.code)
        find = QPushButton('查询 / 刷新')
        find.clicked.connect(self.find)
        bar.addWidget(find)
        manage = QPushButton('管理采集任务')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=project(kind))))
        bar.addWidget(manage)
        layout.addLayout(bar)
        dates = QHBoxLayout()
        self.start, self.end, self.order = QLineEdit(), QLineEdit(), QComboBox()
        self.order.addItems(['最新在前', '最早在前'])
        for field, label in ((self.start, '开始'), (self.end, '截止')):
            accessible(field, 'ST事件' + label + '日期')
            field.setPlaceholderText(label + ' YYYY-MM-DD；留空不限')
            field.returnPressed.connect(self.find)
            dates.addWidget(field)
        dates.addWidget(self.order)
        layout.addLayout(dates)
        self.applied_dates = ('', '', True)
        self.status = hint('正在读取已归档事件…')
        layout.addWidget(self.status)
        self.table = table(['证券', 'ST事件日期', '原名称', '新名称', '来源出现次数', '证监会行业', '通达信行业', '原因'])
        self.timeline = EventTimeline(self.table, KINDS[kind][0] + '（来源栏目，含类型转换）', reason=True)
        self.timeline.add_links(shell, [('公司资料', 'listings'), ('股票更名', 'names_security'), ('查看撤销ST' if kind == 'implementation' else '查看实施ST', 'st_removal' if kind == 'implementation' else 'st_implementation')])
        layout.addWidget(self.timeline, 1)
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
        self.applied_dates = (self.start.text().strip(), self.end.text().strip(), self.order.currentIndex() == 0)
        self.applied, self.after, self.history = self.code.text().strip(), None, []
        self.next_cursor = None
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
        start, end, descending = self.applied_dates
        return self.applied, start, end, self.after, 200, descending

    def apply_navigation_context(self, context):
        security_context(context)
        self.code.setText(context.unified_code)
        self.start.setText(context.start)
        self.end.setText(context.end)
        self.find()

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('events', future)
            else:
                try:
                    result = self.scope.result('events', future)
                    self.timeline.render(result['rows'], (self.applied, self.applied_dates, self.after))
                    rows(self.table, [[r[k] if r[k] is not None else '' for k in ('unified_code', 'event_date', 'old_name', 'new_name', 'source_occurrences', 'csrc_industry', 'tdx_industry', 'reason')]
                                      for r in result['rows']], keys=[r['record_key'] for r in result['rows']])
                    self.timeline.update_selection()
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'第{len(self.history) + 1}页；本页{len(result["rows"])}条；每页最多200条。')
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('events', '查询失败', redact(exc, self.shell.cfg),
                                                                   stale=self.table.rowCount() > 0))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('events', self.shell.runtime, 'st.' + self.kind + '.query',
                                           'list_events', *self.requested)

    def save_ui_state(self):
        return dict(code=self.code.text(), applied=self.applied, after=self.after, history=list(self.history),
                    table=table_identity_state(self.table), dates=(self.start.text(), self.end.text()),
                    applied_dates=self.applied_dates, order=self.order.currentIndex(), view=self.timeline.views.currentIndex(),
                    expanded=list(self.timeline.expanded), position=self.timeline.reader.save_position())

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.applied, self.after, self.history = state['applied'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True
        self.start.setText(state.get('dates', ('', ''))[0])
        self.end.setText(state.get('dates', ('', ''))[1])
        self.applied_dates = tuple(state.get('applied_dates', ('', '', True)))
        self.order.setCurrentIndex(state.get('order', 0))
        self.timeline.views.setCurrentIndex(state.get('view', 0))
        self.timeline.expanded = set(state.get('expanded', []))
        self.timeline.reader.restore_position(state.get('position', 0))


class StUiPlugin(UiPlugin):
    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.st_' + kind, KINDS[kind][0] + '界面',
            provides=('ui.pages.st_' + kind,), description='独立按需创建ST事件浏览页')

    def create_pages(self):
        return (PageContribution('st_' + self.kind, KINDS[self.kind][0], partial(StPage, kind=self.kind),
            '数据浏览', 20, '来源历史ST事件与缺名记录', database_tables=('security_st_event',),
            catalogued=True, category='交易状态', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
