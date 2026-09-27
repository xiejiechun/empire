import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.datasets.trade_calendar import FIRST_DATE, month_dates
from empire.plugins.ui.common import accessible, hint, local_date, rows, table
from empire.plugins.ui.plugin import UiPlugin

WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class TradeCalendarPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        from empire.plugins.ui.queries import QueryScope
        self.query_scope = QueryScope(self)
        self.future = self.query_month = None
        self.last_query = 0
        self.dirty = True
        self.loading = False
        today = datetime.now(CHINA).date()
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("交易日历")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        heading.addStretch()
        manage = QPushButton("管理采集计划")
        manage.clicked.connect(lambda: shell.navigate_management("calendar"))
        heading.addWidget(manage)
        layout.addLayout(heading)
        layout.addWidget(hint("大 A 交易日期 · 巨潮资讯 · 历史起点 1990-12-19"))
        layout.addWidget(hint("未来日期为来源当前安排，后续可能调整。每轮维护本月至下一自然年 12 月；未采集不等于休市。"))
        filters = QHBoxLayout()
        self.previous = QPushButton("上个月")
        self.previous.clicked.connect(lambda: self.move(-1))
        filters.addWidget(self.previous)
        self.year = QSpinBox()
        self.year.setRange(1990, today.year + 1)
        self.year.setValue(today.year)
        self.year.setSuffix(" 年")
        accessible(self.year, "交易日历年份")
        self.year.valueChanged.connect(self.changed)
        filters.addWidget(self.year)
        self.month_selector = QComboBox()
        for month in range(1, 13):
            self.month_selector.addItem(f"{month:02d} 月", month)
        self.month_selector.setCurrentIndex(today.month - 1)
        accessible(self.month_selector, "交易日历月份")
        self.month_selector.currentIndexChanged.connect(self.changed)
        filters.addWidget(self.month_selector)
        self.next = QPushButton("下个月")
        self.next.clicked.connect(lambda: self.move(1))
        filters.addWidget(self.next)
        current = QPushButton("回到本月")
        current.clicked.connect(self.current)
        filters.addWidget(current)
        filters.addStretch()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.summary = hint("正在读取已归档日历……")
        self.summary.setAccessibleName("交易日历查询状态")
        layout.addWidget(self.summary)
        self.table = table(["日期", "星期", "交易安排", "最近内容更新 · 北京时间"])
        self.table.setAccessibleName("交易日历结果")
        layout.addWidget(self.table, 1)
        layout.addWidget(hint("首次采集按月补齐历史；相同安排跳过数据库写入，因此内容更新时间不会随着重复采集变化。"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)

    def selected_month(self):
        return f"{self.year.value():04d}-{self.month_selector.currentData():02d}"

    def save_ui_state(self):
        return {"year": self.year.value(), "month": self.month_selector.currentData()}

    def restore_ui_state(self, state):
        self.loading = True
        self.year.setValue(state["year"])
        self.month_selector.setCurrentIndex(state["month"] - 1)
        self.loading = False
        self.dirty = True

    def set_month(self, year, month):
        self.loading = True
        self.year.setValue(year)
        self.month_selector.setCurrentIndex(month - 1)
        self.loading = False
        self.changed()

    def changed(self):
        if self.loading:
            return
        if self.year.value() == 1990 and self.month_selector.currentData() < 12:
            self.set_month(1990, 12)
            return
        self.reload()

    def current(self):
        today = datetime.now(CHINA).date()
        self.set_month(today.year, today.month)

    def move(self, step):
        index = self.year.value() * 12 + self.month_selector.currentData() - 1 + step
        if 1990 * 12 + 11 <= index <= self.year.maximum() * 12 + 11:
            self.set_month(index // 12, index % 12 + 1)

    def reload(self):
        if self.future is not None:
            self.query_scope.cancel("calendar")
            self.future = None
        self.dirty = True
        self.tick()

    def render(self, result):
        records = {r["trade_date"]: r for r in result["rows"]}
        dates = month_dates(result["month"])
        values = []
        for day in dates:
            record = records.get(day.isoformat())
            state = "交易日" if record and record["is_trade"] else "休市" if record else "未采集"
            values.append([day.isoformat(), WEEKDAYS[day.weekday()], state,
                           local_date(record["updated_at"]) if record else "—"])
        rows(self.table, values)
        trading = sum(r["is_trade"] for r in records.values())
        self.summary.setText(f"{result['month']} · 已采集 {len(records)} / {len(dates)} 天 · "
                             f"交易 {trading} 天 · 休市 {len(records) - trading} 天 · "
                             + ("整月完整" if result["complete"] else "存在未采集日期"))
        self.previous.setEnabled(result["month"] > FIRST_DATE.strftime("%Y-%m"))
        self.next.setEnabled(result["month"] < f"{self.year.maximum()}-12")

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, requested = self.future, self.query_month
            self.future = self.query_month = None
            if requested == self.selected_month():
                try:
                    self.render(self.query_scope.result("calendar", future))
                except Exception as exc:
                    self.summary.setText(self.query_scope.failure_message(
                        "calendar", "日历查询失败", redact(exc, self.shell.cfg),
                        stale=self.table.rowCount() > 0,
                    ))
            else:
                self.query_scope.discard("calendar", future)
                self.dirty = True
        if self.isVisible() and not self.future and (self.dirty or time.monotonic() - self.last_query >= 15):
            self.query_month = self.selected_month()
            self.dirty = False
            self.last_query = time.monotonic()
            self.future = self.query_scope.invoke(
                "calendar", self.shell.runtime, "calendar.query", "month", self.query_month)


class CalendarUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.calendar", "交易日历界面", provides=("ui.pages.calendar",), autostart=True,
        description="交易日历界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("calendar", "交易日历", TradeCalendarPage, "数据浏览", 2,
                             "巨潮 A 股交易日、休市日与月份完整性", catalogued=True,
                             category="基础数据", source="巨潮资讯", cache_policy="lru",
                             management=NavigationTarget(
                                 "collection", NavigationContext(task_id="cninfo-calendar"))),
        )
