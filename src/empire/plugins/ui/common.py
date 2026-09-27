from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from empire.core.time import CHINA
from empire.desktop.theme import TABLE_ROW_HEIGHT

STATUS = {"idle": "待执行", "running": "执行中", "collecting": "正在采集",
          "paused": "已暂停", "complete": "已完成", "error": "失败",
          "awaiting_archive": "等待归档", "stopped": "已停止"}
def stamp(value):
    return datetime.fromtimestamp(value, CHINA).strftime("%m-%d %H:%M:%S") if value else "—"


def elapsed(start, finish):
    if start is None or finish is None:
        return "—"
    seconds = max(0, int(finish - start))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setAccessibleName(f"数据表：{'、'.join(headers)}")
    widget.setAccessibleDescription("使用方向键浏览单元格，空格选择当前行。")
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setDefaultSectionSize(140)
    widget.horizontalHeader().setMinimumSectionSize(100)
    widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(False)
    return widget


def accessible(widget, name, description=""):
    """Give an interactive control a stable screen-reader name."""
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget


def bind_find(parent, field):
    """Use the standard find shortcut without creating page-specific paths."""
    shortcut = QShortcut(QKeySequence.StandardKey.Find, parent)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(lambda: (field.setFocus(), field.selectAll()))
    shortcuts = getattr(parent, "_accessibility_shortcuts", [])
    shortcuts.append(shortcut)
    parent._accessibility_shortcuts = shortcuts
    return shortcut


def rows(widget, values, *, keys=None):
    """Reuse cells and preserve row selections/current cell by stable business keys."""
    pending = getattr(widget, "_pending_identity_state", None)
    if hasattr(widget, "_pending_identity_state"):
        del widget._pending_identity_state
    scroll = pending["vertical"] if pending else widget.verticalScrollBar().value()
    horizontal = pending["horizontal"] if pending else widget.horizontalScrollBar().value()
    previous_keys = getattr(widget, "_row_keys", [])
    previous_current = widget.currentRow(), widget.currentColumn()
    previous_selection = {index.row() for index in widget.selectedIndexes()}
    selected_keys = (set(pending["selected_keys"]) if pending else
                     {previous_keys[index] for index in previous_selection
                      if 0 <= index < len(previous_keys)})
    current_key = (pending["current_key"] if pending else
                   previous_keys[previous_current[0]]
                   if 0 <= previous_current[0] < len(previous_keys) else None)
    current_column = pending["current_column"] if pending else previous_current[1]
    # Callbacks must only see complete data and the final restored selection.
    with QSignalBlocker(widget):
        widget.setRowCount(len(values))
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                text = str(value)
                item = widget.item(i, j)
                if item is None:
                    item = QTableWidgetItem(text)
                    widget.setItem(i, j, item)
                elif item.text() != text:
                    item.setText(text)
                if item.toolTip() != text:
                    item.setToolTip(text)
                item.setTextAlignment((Qt.AlignmentFlag.AlignRight if isinstance(value, (int, float))
                                      else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        widget._row_keys = list(keys) if keys is not None else []
        if keys is not None:
            selection = widget.selectionModel()
            selection.clearSelection()
            positions = {key: index for index, key in enumerate(widget._row_keys)}
            for key in selected_keys:
                if key in positions:
                    selection.select(widget.model().index(positions[key], 0),
                                     QItemSelectionModel.SelectionFlag.Select
                                     | QItemSelectionModel.SelectionFlag.Rows)
            current = positions.get(current_key, -1)
            widget.setCurrentCell(current, current_column if current >= 0 else -1,
                                  QItemSelectionModel.SelectionFlag.NoUpdate)
    widget.verticalScrollBar().setValue(scroll)
    widget.horizontalScrollBar().setValue(horizontal)
    if previous_selection != {index.row() for index in widget.selectedIndexes()}:
        widget.itemSelectionChanged.emit()
    if previous_current != (widget.currentRow(), widget.currentColumn()):
        widget.currentCellChanged.emit(widget.currentRow(), widget.currentColumn(), *previous_current)


def table_identity_state(widget):
    keys = getattr(widget, "_row_keys", [])
    selected = {index.row() for index in widget.selectedIndexes()}
    current = widget.currentRow()
    return {"selected_keys": [keys[index] for index in selected if 0 <= index < len(keys)],
            "current_key": keys[current] if 0 <= current < len(keys) else None,
            "current_column": widget.currentColumn(),
            "vertical": widget.verticalScrollBar().value(),
            "horizontal": widget.horizontalScrollBar().value()}


def restore_table_identity(widget, state):
    widget._pending_identity_state = state


def hint(text=""):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class Pager(QWidget):
    changed = Signal(int)

    def __init__(self, limit=25):
        super().__init__()
        self.offset, self.limit, self.total = 0, limit, 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setAccessibleName("分页状态")
        self.label.setObjectName("muted")
        layout.addWidget(self.label)
        layout.addStretch()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.clicked.connect(lambda: self.changed.emit(max(0, self.offset - self.limit)))
        self.next.clicked.connect(lambda: self.changed.emit(self.offset + self.limit))
        layout.addWidget(self.previous)
        layout.addWidget(self.next)
        self.update_result(0, 0)

    def update_result(self, total, offset):
        self.total, self.offset = total, offset
        self.label.setText(f"共 {total:,} 项 · 第 {offset // self.limit + 1} / "
                           f"{max(1, (total + self.limit - 1) // self.limit)} 页 · 每页 {self.limit} 项")
        self.previous.setEnabled(offset > 0)
        self.next.setEnabled(offset + self.limit < total)


def update_options(combo, values, all_label):
    values = sorted(set(values))
    if [combo.itemData(i) for i in range(1, combo.count())] == values and combo.count():
        return
    selected = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(all_label, "")
    for value in values:
        combo.addItem(value, value)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    combo.blockSignals(False)


def local_date(value):
    if not value:
        return "尚无完整数据"
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=CHINA)
    return date.astimezone(CHINA).strftime("%Y-%m-%d %H:%M")


