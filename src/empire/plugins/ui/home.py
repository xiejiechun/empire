from datetime import UTC, datetime

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

from empire.core.config import redact
from empire.plugins.collection.control import CHINA
from empire.plugins.ui.collection import STATUS, rows, stamp, table


def local_date(value):
    if not value:
        return "尚无完整数据"
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date.astimezone(CHINA).strftime("%Y-%m-%d %H:%M")


class HomePage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
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
        for col, (key, label) in enumerate((("stocks", "股票覆盖"), ("tasks", "采集任务"), ("queue", "待入库数据"))):
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
        for label, route in (("浏览股票列表", "stocks"), ("浏览财经快讯", "news"), ("管理采集任务", "collection"), ("查看运行记录", "history")):
            button = QPushButton(label)
            if route == "stocks":
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
        self.recent = table(["采集任务", "完成时间（北京时间）", "结果", "数据条数"])
        self.recent.setAlternatingRowColors(True)
        self.recent.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.recent, 1)
        self.empty = QLabel("首次使用：前往采集任务执行一次采集，完成入库后即可浏览股票列表。")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        layout.addWidget(self.empty)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        import time
        if getattr(self.shell, "shutting_down", False):
            self.timer.stop()
            return
        for key, future in list(self.futures.items()):
            if future.done():
                try:
                    self.results[key] = future.result()
                    self.results.pop(key + "_error", None)
                except Exception as exc:
                    self.results.pop(key, None)
                    self.results[key + "_error"] = redact(exc, self.shell.cfg)
                del self.futures[key]
        if not self.isVisible():
            return
        self.render()
        if not self.futures and time.monotonic() - self.last_query >= 5:
            self.last_query = time.monotonic()
            for key, capability, method, args in (
                ("stocks", "stocks.query", "list_stocks", ("", 0, 1)),
                ("control", "collection.control", "snapshot", ()),
            ):
                try:
                    self.futures[key] = self.shell.runtime.invoke(capability, method, *args)
                except Exception as exc:
                    self.results.pop(key, None)
                    self.results[key + "_error"] = redact(exc, self.shell.cfg)

    def render(self):
        stock = self.results.get("stocks", {})
        snapshot = stock.get("snapshot")
        self.cards["stocks"].setText(f"{snapshot['row_count']:,}" if snapshot else "—")
        self.hints["stocks"].setText("沪 / 深 / 北 · 最新完整列表" if snapshot else "等待首次采集完成")
        self.data_status.setText("股票列表更新于 " + local_date(snapshot["finished_at"]) + "（北京时间）"
                                 if snapshot else "暂无完整股票列表，可前往采集任务获取。")
        control = self.results.get("control", {})
        jobs = control.get("jobs", [])
        self.cards["tasks"].setText(str(len(jobs)) if "control" in self.results else "—")
        self.hints["tasks"].setText(f"{sum(bool(j['active']) for j in jobs)} 个执行中 · "
                                   f"{sum(j['policy']['enabled'] for j in jobs)} 个已启用")
        plugins = {p["id"]: p for p in self.shell.runtime.snapshot().get("plugins", [])}
        redis = plugins.get("infra.redis", {})
        queued = redis.get("health", {}).get("queued") if redis.get("state") == "RUNNING" else None
        self.cards["queue"].setText(f"{queued:,}" if queued is not None else "—")
        self.hints["queue"].setText("按批次每 60 秒自动入库")
        history = control.get("history", [])
        names = {job["id"]: job["name"] for job in jobs}
        rows(self.recent, [[names.get(h["task_id"], h["task_id"]), stamp(h["finished_at"]),
                           STATUS.get(h["status"], h["status"]), h["result"].get("collected", "—")]
             for h in history[:5]])
        self.empty.setVisible(not history)
        problems = [self.results[k] for k in ("stocks_error", "control_error") if k in self.results]
        if control.get("error"):
            problems.append(redact(control["error"], self.shell.cfg))
        self.notice.setText("需要处理：" + "；".join(problems) if problems else
                            "运行失败时可在运行记录查看原因；服务连接问题请查看系统管理中的运行状态。")
