from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.stocks import MARKET_NAMES
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    restore_table_identity,
    rows,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin

PAGE_SIZE = 200


class StockListPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        from empire.plugins.ui.queries import QueryScope
        self.query_scope = QueryScope(self)
        self.offset = 0
        self.total = 0
        self.future = None
        self.query_spec = None
        self.applied_search = ""
        self.previous_snapshot = None
        self.loaded = False
        self.force_reload = True
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("股票列表")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        heading.addStretch()
        collect = QPushButton("前往采集任务")
        collect.setToolTip("查看股票列表采集进度、设置自动采集计划")
        collect.clicked.connect(lambda: self.shell.navigate_management("stocks"))
        heading.addWidget(collect)
        layout.addLayout(heading)
        self.status = QLabel("正在读取已归档的股票列表…")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)

        filters = QHBoxLayout()
        market_label = QLabel("市场")
        self.market = QComboBox()
        self.market.addItem("全部市场", None)
        for code, name in MARKET_NAMES.items():
            self.market.addItem(f"{name} · {code}", code)
        market_label.setBuddy(self.market)
        self.market.setMinimumWidth(135)
        accessible(self.market, "股票市场筛选")
        filters.addWidget(market_label)
        filters.addWidget(self.market)
        self.search = QLineEdit()
        self.search.setPlaceholderText("代码 / 名称 / 统一代码，如 000001.SZ")
        self.search.setMaxLength(100)
        self.search.setClearButtonEnabled(True)
        accessible(self.search, "搜索股票", "输入代码、名称或统一代码；按 Ctrl+F 可回到此处。")
        bind_find(self, self.search)
        self.search.returnPressed.connect(self.search_changed)
        filters.addWidget(self.search, 1)
        self.find = QPushButton("查询")
        self.find.setObjectName("primary")
        self.find.clicked.connect(self.search_changed)
        filters.addWidget(self.find)
        self.clear = QPushButton("清空搜索")
        self.clear.clicked.connect(self.clear_search)
        filters.addWidget(self.clear)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setToolTip("重新读取当前筛选条件下的最新完整股票列表")
        self.refresh_button.clicked.connect(self.reload)
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)

        result_bar = QHBoxLayout()
        self.result_summary = QLabel("来源：新浪 · 上海 / 深圳 / 北京 A 股")
        self.result_summary.setObjectName("muted")
        self.result_summary.setWordWrap(True)
        result_bar.addWidget(self.result_summary, 1)
        self.copy_button = QPushButton("复制选中行")
        self.copy_button.setToolTip("复制所选股票及列标题，可直接粘贴到表格（Ctrl+C）")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_selection)
        result_bar.addWidget(self.copy_button)
        layout.addLayout(result_bar)
        self.table = QTableWidget(0, 5)
        accessible(self.table, "股票列表结果", "使用方向键浏览，空格选择，Ctrl+C 复制所选行。")
        self.table.setHorizontalHeaderLabels(["代码", "名称", "统一代码", "市场", "来源代码"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(86)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((120, 170, 145, 115, 135)):
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(
            lambda: self.copy_button.setEnabled(bool(self.table.selectedIndexes()))
        )
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_selection)
        self.content = QStackedWidget()
        self.content.addWidget(self.table)
        self.empty = QLabel("正在读取股票列表…")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("muted")
        self.content.addWidget(self.empty)
        self.content.setCurrentWidget(self.empty)
        layout.addWidget(self.content, 1)

        pagination = QHBoxLayout()
        self.page_label = QLabel("每页 200 条")
        self.page_label.setAccessibleName("股票列表分页状态")
        self.page_label.setObjectName("muted")
        pagination.addWidget(self.page_label)
        pagination.addStretch()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.previous.clicked.connect(lambda: self.navigate(-PAGE_SIZE))
        self.next.clicked.connect(lambda: self.navigate(PAGE_SIZE))
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        layout.addLayout(pagination)
        self.market.currentIndexChanged.connect(self.search_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(700)

    def current_query(self):
        return self.applied_search, self.offset, self.market.currentData()

    def save_ui_state(self):
        return {"search": self.search.text(), "applied_search": self.applied_search,
                "market": self.market.currentData(), "offset": self.offset,
                "table": table_identity_state(self.table)}

    def restore_ui_state(self, state):
        self.search.setText(state["search"])
        self.applied_search = state["applied_search"]
        self.market.blockSignals(True)
        self.market.setCurrentIndex(max(0, self.market.findData(state["market"])))
        self.market.blockSignals(False)
        self.offset = state["offset"]
        restore_table_identity(self.table, state["table"])
        self.force_reload = True

    def search_changed(self):
        self.applied_search = self.search.text().strip()
        self.offset = 0
        self.reload()

    def clear_search(self):
        self.search.clear()
        self.search_changed()

    def reload(self):
        if self.future is not None:
            self.query_scope.cancel("stocks")
            self.future = None
        self.force_reload = True
        self.tick()

    def navigate(self, step):
        self.offset = max(0, self.offset + step)
        self.reload()

    def copy_selection(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return
        lines = [[self.table.horizontalHeaderItem(col).text()
                  for col in range(self.table.columnCount())]]
        for row in rows:
            lines.append([self.table.item(row, col).text()
                          for col in range(self.table.columnCount())])
        QApplication.clipboard().setText("\n".join("\t".join(line) for line in lines))
        self.shell.statusBar().showMessage(f"已复制 {len(rows)} 条股票，可粘贴到表格", 4000)

    def tick(self):
        if not self.isVisible() or getattr(self.shell, "shutting_down", False):
            return
        plugins = {p["id"]: p for p in self.shell.runtime.snapshot().get("plugins", [])}
        health = plugins.get("collector.sina_universe", {}).get("health", {})
        state = health.get("status", "stopped")
        if self.future and self.future.done():
            future = self.future
            self.future = None
            try:
                if self.query_spec == self.current_query():
                    result = self.query_scope.result("stocks", future)
                    self.show_result(result)
                    self.loaded = True
                else:
                    self.query_scope.discard("stocks", future)
                    self.force_reload = True
            except Exception as exc:
                self.result_summary.setText(self.query_scope.failure_message(
                    "stocks", "读取失败", redact(exc, self.shell.cfg), stale=self.loaded,
                ) + " · 可点击刷新重试")
                if not self.loaded:
                    self.empty.setText("暂时无法读取股票列表\n请检查系统状态后点击刷新")
                # A failed query is retried only by an explicit refresh or a new snapshot.
                self.loaded = True
                self.previous_snapshot = health.get("snapshot_id")
        ready = plugins.get("data.stocks", {}).get("state") == "RUNNING"
        if not self.future and ready:
            pending_snapshot = health.get("snapshot_id") != self.previous_snapshot and state in (
                "awaiting_archive", "complete"
            )
            if self.force_reload or not self.loaded or pending_snapshot:
                self.force_reload = False
                self.query_spec = self.current_query()
                self.result_summary.setText("正在读取筛选结果…")
                self.future = self.query_scope.invoke(
                    "stocks", self.shell.runtime, "stocks.query", "list_stocks",
                    self.applied_search, self.offset, PAGE_SIZE, self.market.currentData(),
                )
        elif not ready:
            self.result_summary.setText("股票查询服务尚未就绪，请在系统状态中查看服务状态")
        busy = self.future is not None
        self.find.setEnabled(ready and not busy)
        self.refresh_button.setEnabled(ready and not busy)
        self.previous.setEnabled(ready and not busy and self.offset > 0)
        self.next.setEnabled(ready and not busy and self.offset + PAGE_SIZE < self.total)

    def show_result(self, result):
        snapshot = result["snapshot"]
        self.total = result["total"]
        if self.offset and self.offset >= self.total:
            self.offset = max(0, (self.total - 1) // PAGE_SIZE * PAGE_SIZE)
            self.force_reload = True
            return
        if snapshot:
            self.previous_snapshot = result.get("verified_snapshot_id", snapshot["snapshot_id"])
            finished = datetime.fromisoformat(snapshot["finished_at"])
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=CHINA)
            local_time = finished.astimezone(CHINA).strftime("%Y-%m-%d %H:%M:%S")
            self.status.setText(
                f"新浪 A 股 · 当前列表 {snapshot['row_count']:,} 条 · 更新于 {local_time}（北京时间）"
            )
        else:
            self.status.setText("尚无完整股票列表；采集和归档完成后会自动显示。")
        stocks = result["rows"]
        rows(self.table, [[stock["code"], stock["name"], stock["unified_code"],
                          f"{MARKET_NAMES[stock['market']]} ({stock['market']})", stock["source_symbol"]]
                         for stock in stocks],
             keys=[(stock["source"], stock["unified_code"]) for stock in stocks])
        self.content.setCurrentWidget(self.table if stocks else self.empty)
        if not stocks:
            self.empty.setText(
                "没有匹配的股票\n试试其他代码、名称或市场，或清空搜索。" if snapshot else
                "还没有可查看的股票列表\n点击右上角“前往采集任务”，完成首次采集。"
            )
        market = MARKET_NAMES.get(self.market.currentData(), "全部市场")
        query = f" · 搜索“{self.applied_search}”" if self.applied_search else ""
        self.result_summary.setText(f"{market}{query} · 匹配 {self.total:,} 条")
        pages = (self.total + PAGE_SIZE - 1) // PAGE_SIZE
        current = self.offset // PAGE_SIZE + 1 if pages else 0
        visible_range = f"{self.offset + 1}–{self.offset + len(stocks)}" if stocks else "0"
        self.page_label.setText(
            f"第 {current} / {pages} 页 · 显示 {visible_range} 条 · 每页 {PAGE_SIZE} 条"
        )
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + PAGE_SIZE < self.total)


class StockUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.stocks", "股票列表界面", provides=("ui.pages.stocks",), autostart=True,
        description="股票列表界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("stocks", "股票列表", StockListPage, "数据浏览", 0,
                             "查找股票、筛选市场、复制数据 · Alt+2", catalogued=True,
                             category="基础数据", source="新浪财经", cache_policy="lru",
                             management=NavigationTarget(
                                 "collection", NavigationContext(task_id="sina-stocks"))),
        )
