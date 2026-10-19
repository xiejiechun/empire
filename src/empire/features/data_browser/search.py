"""Debounced candidates; selection keeps market identity without querying on page construction."""
from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, QTimer
from PySide6.QtWidgets import QCompleter

from empire.plugins.ui.queries import QueryScope


class CandidateSearch(QObject):
    def __init__(self, owner, field, shell, dataset='stock', selected=None, *, index=False):
        super().__init__(owner)
        self.field, self.shell, self.dataset = field, shell, dataset
        self.selected, self.index = selected, index
        self.scope, self.future, self.requested = QueryScope(owner), None, None
        self.model, self.options = QStringListModel(self), {}
        self.completer = QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        field.setCompleter(self.completer)
        field.setMaxLength(100)
        field.setPlaceholderText('搜索名称或代码，选择带市场的已归档证券' if not index else '搜索指数名称或来源代码')
        # QLineEdit also inserts the completion label. Normalize only after that
        # insertion, so business queries retain the code rather than the label.
        self.completer.activated[str].connect(self.choose, Qt.ConnectionType.QueuedConnection)
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(300)
        self.delay.timeout.connect(self.search)
        field.textEdited.connect(lambda _: self.delay.start())
        field.installEventFilter(self)
        self.poll = QTimer(self)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self.tick)
        self.poll.start()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn and not self.field.text():
            self.delay.start()
        return False

    def search(self):
        if self.scope.closed or not self.field.isVisible():
            return
        self.requested = self.field.text().strip()
        args = ('indices', self.requested, None, 20) if self.index else (self.requested, self.dataset, 20)
        self.future = self.scope.invoke('candidates', self.shell.runtime,
            'indices.query' if self.index else 'stocks.query', 'browse' if self.index else 'candidates', *args)

    def tick(self):
        if self.scope.closed:
            self.poll.stop()
            return
        if not self.future or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            result = self.scope.result('candidates', future)
            if self.requested != self.field.text().strip():
                return
            records = result['rows'] if self.index else result
            self.options = {f'{r["index_code"]}  {r["index_name"]}' if self.index else
                f'{r["unified_code"]}  {r["name"]}': r for r in records}
            self.model.setStringList(list(self.options))
            if self.field.hasFocus():
                self.completer.complete()
        except Exception:
            self.field.setToolTip('候选暂不可用，仍可输入已知代码查询；候选查询不启动采集。')

    def choose(self, label):
        record = self.options.get(label)
        if not record:
            return
        self.field.setText(record['index_code'] if self.index else record['unified_code'][:6])
        self.field.setToolTip(label)
        if self.selected:
            self.selected(record)
