"""Paged directory selection backed by one registered formal query."""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from empire.core.redaction import redact
from empire.plugins.ui.common import restore_table_identity, rows, table, table_identity_state
from empire.plugins.ui.preview_layout import compact_columns
from empire.plugins.ui.queries import QueryScope


class DirectoryPanel(QWidget):
    selected = Signal(object)

    def __init__(self, shell, capability, method, key, fields, headers, *, prefix=()):
        super().__init__()
        self.shell, self.capability, self.method, self.key, self.fields, self.prefix = shell, capability, method, key, fields, prefix
        self.scope = QueryScope(self)
        self.search, self.after, self.history, self.next_cursor = '', None, [], None
        self.future, self.requested, self.records, self.preferred = None, None, [], None
        self.dirty = True
        layout = QVBoxLayout(self)
        self.table = table(headers)
        self.table.setAccessibleName('业务目录')
        compact_columns(self.table, [90, 150, 80, 70][:len(headers)], 1)
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table, 1)
        self.status = QLabel('正在读取目录')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页目录'), QPushButton('下一页目录')
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def find(self, search='', preferred=None):
        self.search, self.preferred, self.after, self.history, self.dirty = search, preferred, None, [], True

    def refresh(self):
        self.preferred = self.records[self.table.currentRow()][self.key] if 0 <= self.table.currentRow() < len(self.records) else None
        self.dirty = True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def select(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.records):
            self.selected.emit(self.records[index])

    def tick(self):
        if self.scope.closed or getattr(self.shell, 'shutting_down', False):
            self.timer.stop()
            self.scope.close()
            return
        spec = self.prefix + (self.search, self.after if self.prefix else self.after or '', 200)
        if self.future and self.future.done():
            future, self.future = self.future, None
            if spec != self.requested:
                self.scope.discard('directory', future)
            else:
                try:
                    result = self.scope.result('directory', future)
                    self.records, self.next_cursor = result['rows'], result['next']
                    rows(self.table, [[r[k] for k in self.fields] for r in self.records], keys=[r[self.key] for r in self.records])
                    if self.records:
                        preferred = self.preferred or self.table.item(max(0, self.table.currentRow()), 0).text()
                        self.table.selectRow(next((i for i, r in enumerate(self.records) if r[self.key] == preferred), 0))
                        self.select()
                    else:
                        self.selected.emit(None)
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'目录第{len(self.history)+1}页 · {len(self.records)}项')
                except Exception as exc:
                    self.status.setText('目录查询失败：' + redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, spec
            self.future = self.scope.invoke('directory', self.shell.runtime, self.capability, self.method, *spec)

    def save(self):
        return dict(search=self.search, after=self.after, history=list(self.history),
                    table=table_identity_state(self.table))

    def restore(self, state):
        self.search, self.after, self.history = state['search'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True
