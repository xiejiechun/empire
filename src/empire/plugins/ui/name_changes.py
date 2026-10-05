"""Lazy cursor-paged browsers for two distinct name meanings."""
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from empire.contracts.name_changes import KINDS, project
from empire.contracts.plugin import PluginManifest
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
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class NamePage(QWidget):
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
        layout.addWidget(hint('来源更名日期及旧新名称；空白表示来源未给。采集完成不等于历史名称回放通过。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), '更名证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('六位证券代码或前缀')
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.find)
        bar.addWidget(self.code)
        find = QPushButton('查询 / 刷新')
        find.clicked.connect(self.find)
        bar.addWidget(find)
        manage = QPushButton('管理采集任务')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=project(kind))))
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('正在读取已归档事件…')
        layout.addWidget(self.status)
        self.table = table(['证券', '更名日期', '原名称', '新名称', '来源出现次数'])
        layout.addWidget(self.table, 1)
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
        return self.applied, '', '', self.after, 200

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
                    rows(self.table, [[r[k] if r[k] is not None else '' for k in ('unified_code', 'event_date', 'old_name', 'new_name', 'source_occurrences')]
                                      for r in result['rows']], keys=[r['record_key'] for r in result['rows']])
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'第{len(self.history) + 1}页；本页{len(result["rows"])}条；每页最多200条。')
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('events', '查询失败', redact(exc, self.shell.cfg),
                                                                   stale=self.table.rowCount() > 0))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('events', self.shell.runtime, 'names.' + self.kind + '.query',
                                           'list_events', *self.requested)

    def save_ui_state(self):
        return dict(code=self.code.text(), applied=self.applied, after=self.after, history=list(self.history),
                    table=table_identity_state(self.table))

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.applied, self.after, self.history = state['applied'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True


class NameUiPlugin(UiPlugin):
    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.names_' + kind, KINDS[kind][0] + '界面',
            provides=('ui.pages.names_' + kind,), description='独立按需创建更名事件浏览页')

    def create_pages(self):
        return (PageContribution('names_' + self.kind, KINDS[self.kind][0], partial(NamePage, kind=self.kind),
            '数据浏览', 20, '来源历史更名事件与缺名记录', database_tables=('security_name_change',),
            catalogued=True, category='证券基础', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
