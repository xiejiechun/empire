from copy import deepcopy
from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from empire.core.redaction import redact
from empire.desktop.theme import PAGE_SPACING
from empire.plugins.ui.common import hint
from empire.plugins.ui.queries import QueryScope

SECTIONS = {
    "tasks": ("采集任务", "设置执行计划、开始采集与恢复断点，在这里统一管理。"),
    "sites": ("站点访问规则", "按出口 IP 控制对同一站点的访问节奏，同站点的采集任务共享规则。"),
    "history": ("运行记录", "采集、归档与错误分别查看；仅存 Redis，按项目独立限量保留。"),
}



class CollectionView(QWidget):
    """Shared query/action lifecycle; each concrete page owns its controls."""
    def __init__(self, shell):
        section = self.section
        super().__init__()
        if section not in SECTIONS:
            raise ValueError(f"Unknown collection section: {section}")
        self.shell, self.section = shell, section
        self.query_scope = QueryScope(self)
        self.query = self.action = self.action_context = None
        self.data = None
        self.offset = 0
        self.next_query = 0
        self._loading = False
        self.buttons, self.run_buttons = [], []
        self.initialize_state()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(PAGE_SPACING)
        self.title = QLabel(SECTIONS[section][0])
        self.title.setObjectName("pageTitle")
        layout.addWidget(self.title)
        layout.addWidget(hint(SECTIONS[section][1]))
        self.summary = hint("正在连接采集管理服务……")
        layout.addWidget(self.summary)
        layout.addWidget(self.build_view(), 1)
        self.feedback = self.action_feedback("configure")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(700)
        self._update_buttons()

    def filters_changed(self):
        self.offset = 0
        if self.query is not None:
            self.query_scope.cancel("workspace")
        self.query = None
        self.data = None
        self.next_query = monotonic() + .25
        self._update_buttons()

    def change_page(self, offset):
        self.filters_changed()
        self.offset = offset
        self.next_query = 0

    def submit(self, method, *args):
        if self.action:
            return
        target = self.action_feedback(method)
        try:
            self.action = self.shell.runtime.invoke("collection.control", method, *args)
            self.action_context = (method, deepcopy(args), target)
            target.setText("正在保存……" if method.startswith("configure") else "正在执行……")
        except Exception as exc:
            target.setText(redact(exc, self.shell.cfg))
        self._update_buttons()

    def _finish_action(self):
        method, args, target = self.action_context
        try:
            result = self.action.result()
            text = result if isinstance(result, str) and len(result) != 32 else "任务已启动"
            text = self.apply_action_result(method, args, text)
            target.setText(text)
            # Ignore snapshots started before this change; they may contain old settings.
            if self.query is not None:
                self.query_scope.cancel("workspace")
            self.query = None
            self.next_query = 0
        except Exception as exc:
            target.setText("操作失败：" + redact(exc, self.shell.cfg))
        self.action = self.action_context = None

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.action and self.action.done():
            self._finish_action()
        if self.query and self.query.done():
            try:
                self.data = self.query_scope.result("workspace", self.query)
                self.render()
            except Exception as exc:
                self.summary.setText(self.query_scope.failure_message(
                    "workspace", "采集管理服务未就绪", redact(exc, self.shell.cfg),
                    stale=self.data is not None,
                ))
            self.query = None
        self._update_buttons()
        if self.isVisible() and self.query is None and monotonic() >= self.next_query:
            self.query = self.query_scope.invoke(
                "workspace", self.shell.runtime,
                "collection.control", "workspace", *self._query_args())
            self.next_query = monotonic() + 3

    def render(self):
        text = self.summary_text()
        error = self.data.get("error")
        self.summary.setText(text + (" · " + redact(error, self.shell.cfg) if error else ""))
        if "total" in self.data:
            self.offset = self.data["offset"]
            pager = self.pager
            pager.update_result(self.data["total"], self.offset)
        self.render_content()
        self._update_buttons()

    def _update_buttons(self):
        pass

    def initialize_state(self):
        pass

    def action_feedback(self, method):
        return self.summary

    def apply_action_result(self, method, args, text):
        return text
