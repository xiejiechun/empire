"""Lazy daily-index browser with applied filters separate from editable drafts."""

from datetime import datetime, timedelta

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.features.index_prices.chart import IndexPriceChart
from empire.features.index_prices.contract import volume_amount_valid
from empire.plugins.ui.common import accessible, rows
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import DataNote, QueryForm
from empire.plugins.ui.preview_search import CandidateSearch
from empire.plugins.ui.queries import QueryScope


class IndexPricePage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_after, self.history = None, None, []
        self.future, self.requested, self.dirty = None, None, True
        self.applied = ('', '', '')
        self.chart_future, self.chart_requested, self.chart_dirty = None, None, False
        layout = QVBoxLayout(self)
        title = QLabel("同花顺指数历史日行情")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = DataNote('已归档指数日线 · 选择指数和范围查看K线与量额。',
            "查看已归档收盘日线。代码使用同花顺目录，如上证1A0001、沪深300为1B0300；量额保留来源口径。缺失价格不代填，矛盾原值保留并标注价格关系异常，受影响日期不用于依赖四价的策略。"
        )
        layout.addWidget(note)
        self.code = accessible(QLineEdit(), "指数行情同花顺代码")
        self.start = accessible(QLineEdit(), "指数行情开始日期")
        self.end = accessible(QLineEdit(), "指数行情结束日期")
        self.candidates = CandidateSearch(self, self.code, shell, index=True)
        for widget, hint, maximum in [
            (self.code, "指数代码；空=全部已存指数", 6),
            (self.start, "开始 YYYY-MM-DD", 10),
            (self.end, "结束 YYYY-MM-DD", 10),
        ]:
            widget.setPlaceholderText(hint)
            widget.setMaxLength(100 if widget is self.code else maximum)
            widget.returnPressed.connect(self.find)
        actions = []
        for label, action in [
            ("查询", self.find),
            ("刷新", self.refresh),
            ("采集任务", lambda: shell.navigate_management("index_prices")),
        ]:
            button = QPushButton(label)
            button.clicked.connect(action)
            actions.append(button)
        layout.addWidget(QueryForm([('指数名称 / 来源代码', self.code),
            ('开始日期', self.start), ('截止日期', self.end)], actions))
        ranges = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(['最近一年', '最近一季', '最近一月', '自定义'])
        self.preset.currentIndexChanged.connect(self.set_preset)
        ranges.addWidget(QLabel('图表日期范围'))
        ranges.addWidget(self.preset)
        layout.addLayout(ranges)
        self.set_preset(0)
        self.status = QLabel("正在读取已归档日线…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = accessible(QTableWidget(0, 10), "指数历史日行情结果")
        self.table.setHorizontalHeaderLabels(
            [
                "日期",
                "指数代码",
                "名称",
                "开盘",
                "最高",
                "最低",
                "收盘",
                "成交量（来源值）",
                "成交额（元）",
                "数据质量",
            ]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.views = QTabWidget()
        self.chart = IndexPriceChart()
        self.views.addTab(self.chart, '行情图')
        self.views.addTab(self.table, '日线明细')
        layout.addWidget(self.views, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton("上一页"), QPushButton("下一页")
        self.previous.clicked.connect(self.back)
        self.next.clicked.connect(self.forward)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def find(self):
        self.applied = tuple(w.text().strip() for w in (self.code, self.start, self.end))
        self.after, self.history, self.dirty = None, [], True
        self.chart_dirty = bool(self.applied[0])

    def refresh(self):
        self.dirty = True
        self.chart_dirty = bool(self.applied[0])

    def set_preset(self, index):
        if index < 3:
            today = datetime.now(CHINA).date()
            self.end.setText(today.isoformat())
            self.start.setText((today-timedelta(days=(365, 90, 30)[index])).isoformat())

    def apply_navigation_context(self, context):
        if not context.index_code or context.unified_code:
            raise ValueError('指数行情需要同花顺指数身份')
        self.code.setText(context.index_code)
        if context.start:
            self.start.setText(context.start)
        if context.end:
            self.end.setText(context.end)
        self.find()

    def forward(self):
        if self.next_after:
            self.history.append(self.after)
            self.after, self.dirty = self.next_after, True

    def back(self):
        if self.history:
            self.after, self.dirty = self.history.pop(), True

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.scope.close()
            self.timer.stop()
            return
        if self.chart_future and self.chart_future.done():
            future, self.chart_future = self.chart_future, None
            if self.chart_requested != self.applied:
                self.scope.discard('chart', future)
            else:
                try:
                    self.chart.set_result(self.scope.result('chart', future))
                except Exception as exc:
                    self.chart.identity.setText('图表范围加载失败：' + redact(exc, self.shell.cfg)
                        + '；原图保留其原始身份，可核对日线明细。')
        if self.isVisible() and self.chart_dirty and not self.chart_future:
            self.chart_dirty, self.chart_requested = False, self.applied
            self.chart_future = self.scope.invoke('chart', self.shell.runtime, 'index.prices.query', 'chart_series', *self.applied)
        spec = (*self.applied, self.after, 200)
        if self.future and self.future.done():
            future, self.future = self.future, None
            if spec != self.requested:
                self.scope.discard("prices", future)
            else:
                try:
                    result = self.scope.result("prices", future)
                    values, keys = [], []
                    for row in result["rows"]:
                        values.append(
                            [
                                row["trade_date"].isoformat(),
                                row["index_code"],
                                row["name"] or row["index_code"],
                            ]
                            + [
                                "来源未提供" if row[k] is None else str(row[k])
                                for k in ("open", "high", "low", "close", "volume", "amount")
                            ]
                            + [("价格关系异常" if not row["price_relation_valid"] else
                               "来源缺少价格" if any(row[k] is None for k in ("open", "high", "low"))
                               else "关系正常")
                               + ("；来源缺少成交额" if row["amount"] is None else "")
                               + ("；量额异常" if not volume_amount_valid([row["volume"], row["amount"]]) else "")]
                        )
                        keys.append((str(row["trade_date"]), row["index_code"]))
                    rows(self.table, values, keys=keys)
                    self.next_after = result["next"]
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_after))
                    self.status.setText(
                        f"第{len(self.history) + 1}页，本页{len(values)}条；只读已归档行情。"
                        + ("" if values else "暂无匹配记录，请检查日期、代码及采集进度。")
                    )
                except Exception as exc:
                    self.status.setText(
                        self.scope.failure_message(
                            "prices",
                            "查询失败",
                            redact(exc, self.shell.cfg),
                            stale=self.table.rowCount() > 0,
                        )
                    )
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, spec
            self.future = self.scope.invoke(
                "prices", self.shell.runtime, "index.prices.query", "browse", *spec
            )

    def save_ui_state(self):
        return dict(
            drafts=[w.text() for w in (self.code, self.start, self.end)],
            applied=self.applied,
            after=self.after,
            history=self.history,
            view=self.views.currentIndex(), preset=self.preset.currentIndex(),
        )

    def restore_ui_state(self, state):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(state.get('preset', 3))
        self.preset.blockSignals(False)
        for widget, value in zip((self.code, self.start, self.end), state["drafts"], strict=True):
            widget.setText(value)
        self.applied, self.after, self.history = (
            tuple(state["applied"]),
            state["after"],
            state["history"],
        )
        self.dirty = True
        self.views.setCurrentIndex(state.get('view', 0))
        self.chart_dirty = bool(self.applied[0])


class IndexPriceUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.index_prices",
        "指数日行情界面",
        provides=("ui.pages.index_prices",),
        description="按需创建日线范围查询",
    )

    def create_pages(self):
        return (
            PageContribution(
                "index_prices",
                "同花顺指数历史日行情",
                IndexPricePage,
                "数据浏览",
                12,
                "历史开高低收及来源量额；逐年补缺、近期修订",
                database_tables=("index_daily_price", "index_price_year"),
                catalogued=True,
                category="指数数据",
                source="同花顺",
                cache_policy="lru",
                management=NavigationTarget(
                    "collection", NavigationContext(task_id="ths-index-prices")
                ),
            ),
        )
