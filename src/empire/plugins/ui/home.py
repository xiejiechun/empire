
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.core.redaction import redact
from empire.plugins.ui.common import STATUS, rows, stamp, table
from empire.plugins.ui.queries import QueryScope


class HomePage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.query_scope = QueryScope(self)
        self.futures = {}
        self.results = {}
        self.last_query = 0
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        title = QLabel("工作台")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("查看数据更新情况，继续常用工作。")
        note.setObjectName("muted")
        layout.addWidget(note)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.cards, self.hints = {}, {}
        for col, (key, label) in enumerate((("tasks", "采集项目"), ("running", "正在执行"), ("errors", "失败任务"), ("queue", "待归档消息"))):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 18, 18, 18)
            heading = QLabel(label)
            heading.setObjectName("muted")
            box.addWidget(heading)
            value = QLabel("—")
            value.setObjectName("cardValue")
            box.addWidget(value)
            hint = QLabel("正在读取状态")
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            box.addWidget(hint)
            grid.addWidget(card, 0, col)
            self.cards[key], self.hints[key] = value, hint
        layout.addLayout(grid)
        actions = QHBoxLayout()
        for label, route in (("浏览数据目录", "catalog"), ("管理采集任务", "collection"), ("查看运行记录", "history"), ("站点访问规则", "sites")):
            button = QPushButton(label)
            if route == "catalog":
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, target=route: shell.navigate(target))
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.data_status = QLabel("正在读取最近数据更新时间……")
        self.data_status.setWordWrap(True)
        layout.addWidget(self.data_status)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        title = QLabel("最近采集")
        title.setObjectName("sectionTitle")
        row.addWidget(title)
        row.addStretch()
        layout.addLayout(row)
        self.recent = table(["采集任务", "完成时间（北京时间）", "结果", "采集记录数"])
        self.recent.setAlternatingRowColors(True)
        self.recent.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.recent, 1)
        self.empty = QLabel("首次使用：在数据目录了解已接入的数据，在采集任务中启用并执行相应项目。")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        layout.addWidget(self.empty)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        import time
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        for key, future in list(self.futures.items()):
            if future.done():
                try:
                    self.results[key] = self.query_scope.result(key, future)
                    self.results.pop(key + "_error", None)
                except Exception as exc:
                    self.results[key + "_error"] = self.query_scope.failure_message(
                        key, "读取失败", redact(exc, self.shell.cfg),
                        stale=key in self.results,
                    )
                del self.futures[key]
        if not self.isVisible():
            return
        self.render()
        if not self.futures and time.monotonic() - self.last_query >= 5:
            self.last_query = time.monotonic()
            for key, capability, method, args in (
                ("control", "collection.control", "workspace", ("overview",)),
            ):
                self.futures[key] = self.query_scope.invoke(
                    key, self.shell.runtime, capability, method, *args)

    def render(self):
        control = self.results.get("control", {})
        counts = control.get("counts", {})
        self.cards["tasks"].setText(str(counts.get("total", "—")))
        self.hints["tasks"].setText(f"{len(control.get('sources', []))} 个来源组 · {len(control.get('categories', []))} 个业务分类")
        self.cards["running"].setText(str(counts.get("running", "—")))
        self.hints["running"].setText("当前活动采集 · 同一任务不重叠")
        self.cards["errors"].setText(str(counts.get("error", "—")))
        self.hints["errors"].setText("已启用任务的最近运行失败")
        self.data_status.setText(f"{counts.get('disabled', 0)} 个任务已停用 · 配置保存在 MySQL · 数据按业务类型独立归档")
        plugins = {p["id"]: p for p in self.shell.runtime.snapshot().get("plugins", [])}
        redis = plugins.get("infra.redis", {})
        queued = redis.get("health", {}).get("queued") if redis.get("state") == "RUNNING" else None
        self.cards["queue"].setText(f"{queued:,}" if queued is not None else "—")
        self.hints["queue"].setText("Redis 业务消息数 · 一条可包含多条记录")
        history = control.get("history", [])
        names = {job["id"]: job["name"] for job in control.get("projects", [])}
        rows(self.recent, [[names.get(h["task_id"], h["task_id"]), stamp(h["finished_at"]),
                           STATUS.get(h["status"], h["status"]), h["result"].get("collected", "—")]
             for h in history[:5]])
        self.empty.setVisible(not history)
        problems = [self.results[k] for k in ("control_error",) if k in self.results]
        if control.get("error"):
            problems.append(redact(control["error"], self.shell.cfg))
        problems.extend(f"{p['name']}：{redact(p.get('error') or '运行异常', self.shell.cfg)}"
                        for p in plugins.values() if p.get("state") in ("FAILED", "DEGRADED", "BLOCKED"))
        self.notice.setText("需要处理：" + "；".join(problems) if problems else
                            "运行失败时可在运行记录查看原因；服务连接问题请查看系统设置中的运行状态。")
