"""Explicit log reset shared by the three operational history views."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QWidget

from empire.core.redaction import redact
from empire.plugins.ui.common import hint


class LogClearBar(QWidget):
    def __init__(self, shell, selector, label, capability, method, args, refresh, busy=lambda: False):
        super().__init__()
        self.shell, self.selector, self.label = shell, selector, label
        self.capability, self.method, self.args = capability, method, args
        self.refresh, self.busy, self.future = refresh, busy, None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton('清空日志')
        self.button.setAccessibleName(f'清空{label}')
        self.button.clicked.connect(self.clear)
        layout.addWidget(self.button)
        self.feedback = hint()
        layout.addWidget(self.feedback, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def clear(self):
        if self.future or self.busy() or getattr(self.shell, 'shutting_down', False):
            return
        project = self.selector.currentData() or '*'
        name = self.selector.itemText(self.selector.currentIndex())
        message = (f'清空“{name}”的全部{self.label}，包括所有分页和运行结果？\n'
                   '仅删除日志，不改变任务、断点、待归档数据或已归档业务数据。\n'
                   '清空错误日志不表示问题已修复。' if self.label == '错误记录' else
                   f'清空“{name}”的全部{self.label}，包括所有分页和运行结果？\n'
                   '仅删除日志，不改变任务、断点、待归档数据或已归档业务数据。')
        if QMessageBox.question(self, '清空日志', message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.future = self.shell.runtime.invoke(self.capability, self.method, *self.args(project))
            self.feedback.setText(f'正在清空{name}的{self.label}…')
            self.button.setEnabled(False)
        except Exception as exc:
            self.feedback.setText('清空失败：' + redact(exc, self.shell.cfg))

    def tick(self):
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                count = future.result()
                self.feedback.setText(f'已清空 {count} 条{self.label}；随后产生的日志继续显示。')
                self.refresh()
            except Exception as exc:
                self.feedback.setText('清空失败：' + redact(exc, self.shell.cfg))
        self.button.setEnabled(not self.future and not self.busy()
                               and not getattr(self.shell, 'shutting_down', False))
