"""Small responsive forms and readable compact directories for data previews."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class QueryForm(QWidget):
    """Keep field captions visible and wrap fields before values become clipped."""
    def __init__(self, fields, actions=(), parent=None):
        super().__init__(parent)
        self.fields, self.actions, self.columns = [], list(actions), None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        for caption, control in fields:
            group = QWidget(self)
            layout = QVBoxLayout(group)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            label = QLabel(caption)
            label.setBuddy(control)
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(label)
            layout.addWidget(control)
            self.fields.append(group)
        self.arrange()

    def arrange(self):
        columns = min(len(self.fields), max(1, self.width() // 150))
        if columns == self.columns:
            return
        self.columns = columns
        for widget in self.fields + self.actions:
            self.grid.removeWidget(widget)
        for index, widget in enumerate(self.fields):
            self.grid.addWidget(widget, index // columns, index % columns)
        row = (len(self.fields) + columns - 1) // columns
        for index, widget in enumerate(self.actions):
            self.grid.addWidget(widget, row + index // columns, index % columns)
        for column in range(len(self.fields)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.arrange)


def compact_columns(widget, widths, stretch):
    header = widget.horizontalHeader()
    header.setMinimumSectionSize(50)
    for column, width in enumerate(widths):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        widget.setColumnWidth(column, width)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)


def fit_directory(widget, records, maximum=170):
    """One-result searches should leave space for the actual report or profile."""
    header = widget.horizontalHeader().height()
    height = header + min(max(1, len(records)), 4) * widget.verticalHeader().defaultSectionSize() + 6
    widget.setMaximumHeight(min(maximum, height))


class DataNote(QWidget):
    def __init__(self, summary, detail, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        label = QLabel(summary)
        label.setWordWrap(True)
        bar.addWidget(label, 1)
        button = QPushButton('数据说明')
        button.setCheckable(True)
        bar.addWidget(button)
        layout.addLayout(bar)
        self.detail = QLabel(detail)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setVisible(False)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        button.toggled.connect(self.detail.setVisible)
        layout.addWidget(self.detail)


class DetailSplit(QSplitter):
    """Narrow screens use an explicit detail tab, retaining the same widgets."""
    def __init__(self, views, detail, title='所选详情'):
        super().__init__(Qt.Orientation.Horizontal)
        self.views, self.detail, self.title, self.narrow = views, detail, title, None
        self.preferred_view = None
        self.addWidget(views)
        self.addWidget(detail)
        self.setSizes([430, 700])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 780
        if narrow == self.narrow:
            return
        self.narrow = narrow
        if narrow:
            self.views.addTab(self.detail, self.title)
            if self.preferred_view is not None:
                self.views.setCurrentIndex(self.preferred_view)
                self.preferred_view = None
        else:
            if self.views.currentWidget() is self.detail:
                self.preferred_view = self.views.indexOf(self.detail)
            index = self.views.indexOf(self.detail)
            if index >= 0:
                self.views.removeTab(index)
            self.addWidget(self.detail)
            self.setSizes([430, 700])

    def show_detail(self):
        if self.narrow:
            self.views.setCurrentWidget(self.detail)

    def restore_view(self, index):
        self.preferred_view = index
        if self.narrow is not None and index < self.views.count():
            self.views.setCurrentIndex(index)
            self.preferred_view = None
