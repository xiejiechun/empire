"""Browse archived TDX source records without inferring current trading status."""
from PySide6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    hint,
    local_date,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope
from empire.plugins.ui.suspension_preview import SuspensionPreview

SORT_FIELDS = ("code", "name", "suspended_at", "resumed_at", "source_note", "reason")


class SuspensionsPage(SuspensionPreview, QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.query_scope = QueryScope(self)
        self.page = 0
        self.records = []
        self.future = self.query_spec = None
        self.coverage_future = None
        self.coverage = None
        self.dirty = True
        self.sort_by, self.direction = "code", "asc"
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("历史停复牌")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        heading.addStretch()
        manage = QPushButton("管理采集计划")
        manage.clicked.connect(lambda: shell.navigate_management("suspensions"))
        heading.addWidget(manage)
        layout.addLayout(heading)
        layout.addWidget(hint("通达信 · 沪深 A 股 · 已归档来源记录 · 时间为北京时间"))
        layout.addWidget(hint("同一次停牌可能有停牌、复牌等多条来源记录；复牌时间未提供不代表目前仍停牌。"))
        filters = QHBoxLayout()
        self.market = accessible(QComboBox(), "停复牌市场")
        for label, value in (("全部市场", ""), ("上海", "SH"), ("深圳", "SZ")):
            self.market.addItem(label, value)
        filters.addWidget(self.market)
        self.code = accessible(QLineEdit(), "停复牌证券代码")
        self.code.setPlaceholderText("证券代码（支持前缀）")
        self.code.setMaxLength(6)
        self.code.setClearButtonEnabled(True)
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.search)
        filters.addWidget(self.code, 1)
        layout.addLayout(filters)
        query = QPushButton("查询 / 刷新")
        query.clicked.connect(self.search)
        filters.addWidget(query)
        body = self.body_layout = QHBoxLayout()
        sidebar = self.install_calendar_sidebar(layout)
        month_bar = QHBoxLayout()
        self.year = accessible(QSpinBox(), "来源日历年份")
        self.year.setRange(2004, 9999)
        self.year.setValue(QDate.currentDate().year())
        self.year.setKeyboardTracking(False)
        self.month = accessible(QComboBox(), "来源日历月份")
        self.month.addItems([f"{i} 月" for i in range(1, 13)])
        self.month.setCurrentIndex(QDate.currentDate().month() - 1)
        month_bar.addWidget(self.year)
        month_bar.addWidget(self.month)
        sidebar.addLayout(month_bar)
        self.calendar = accessible(QCalendarWidget(), "来源日期日历")
        self.calendar.setMinimumDate(QDate(2004, 12, 27))
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setGridVisible(True)
        self.calendar.setFixedWidth(252)
        sidebar.addWidget(self.calendar)
        self.year.valueChanged.connect(self.show_month)
        self.month.currentIndexChanged.connect(self.show_month)
        self.calendar.currentPageChanged.connect(self.sync_month)
        self.calendar.selectionChanged.connect(self.select_day)
        self.calendar.clicked.connect(
            lambda _: self.select_day() if self.all_dates.isChecked() else None)
        actions = QHBoxLayout()
        today = QPushButton("今天")
        today.clicked.connect(self.go_today)
        actions.addWidget(today)
        self.all_dates = QCheckBox("全部历史")
        self.all_dates.toggled.connect(self.search)
        actions.addWidget(self.all_dates)
        sidebar.addLayout(actions)
        explanation = hint("按通达信来源日历日期查询。\n停牌、复牌时间保留来源原值。\n点击日期立即查询，点击表头排序。")
        explanation.setFixedWidth(252)
        sidebar.addWidget(explanation)
        sidebar.addStretch()
        body.addWidget(self.calendar_sidebar)
        results = QVBoxLayout()
        body.addLayout(results, 1)
        layout.addLayout(body, 1)
        self.status = hint("等待读取历史停复牌……")
        results.addWidget(self.status)
        self.coverage_status = hint("正在核实来源日历补查进度……")
        results.addWidget(self.coverage_status)
        self.table = table(["证券代码", "证券简称", "停牌时间", "复牌时间", "说明", "原因"])
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(65)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((85, 90, 145, 145, 105)):
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self.sort_column)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.install_preview(results)
        navigation = QHBoxLayout()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        navigation.addWidget(self.previous)
        navigation.addWidget(self.next)
        navigation.addStretch()
        results.addLayout(navigation)
        self.detail = accessible(QPlainTextEdit(), "停复牌完整来源记录")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择记录查看完整说明和原因。")
        results.addWidget(self.detail)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)
        self.applied = self.draft_spec()

    def draft_spec(self):
        day = self.calendar.selectedDate().toString("yyyy-MM-dd")
        return (self.market.currentData(), self.code.text().strip(),
                None if self.all_dates.isChecked() else day,
                None if self.all_dates.isChecked() else day,
                51, self.page * 50, self.sort_by, self.direction)

    def spec(self):
        return (*self.applied[:4], 51, self.page * 50, self.sort_by, self.direction)

    def show_month(self, *_):
        self.calendar.setCurrentPage(self.year.value(), self.month.currentIndex() + 1)

    def sync_month(self, year, month):
        with QSignalBlocker(self.year), QSignalBlocker(self.month):
            self.year.setValue(year)
            self.month.setCurrentIndex(month - 1)

    def select_day(self):
        with QSignalBlocker(self.all_dates):
            self.all_dates.setChecked(False)
        self.search()

    def go_today(self):
        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.showToday()
        self.select_day()

    def sort_column(self, column):
        field = SORT_FIELDS[column]
        self.direction = "desc" if self.sort_by == field and self.direction == "asc" else "asc"
        self.sort_by = field
        self.table.horizontalHeader().setSortIndicator(
            column, Qt.SortOrder.AscendingOrder if self.direction == "asc" else Qt.SortOrder.DescendingOrder)
        self.search()

    def search(self):
        self.page = 0
        self.applied = self.draft_spec()
        self.month_dirty = True
        self.reload()

    def move(self, step):
        self.page = max(0, self.page + step)
        self.reload()

    def reload(self):
        self.query_scope.cancel("suspensions")
        self.future = self.query_spec = None
        self.dirty = True
        self.tick()

    def save_ui_state(self):
        return {"spec": self.draft_spec(), "applied": self.spec(), "view": self.views.currentIndex(), "day": self.calendar.selectedDate().toString("yyyy-MM-dd"),
                "month": (self.calendar.yearShown(), self.calendar.monthShown()),
                "table": table_identity_state(self.table), "cards_position": self.cards.save_position()}

    def restore_ui_state(self, state):
        market, code, start, _, _, offset, sort_by, direction = state["spec"]
        self.market.setCurrentIndex(self.market.findData(market))
        self.code.setText(code)
        with QSignalBlocker(self.calendar), QSignalBlocker(self.all_dates):
            self.calendar.setSelectedDate(QDate.fromString(state['day'], "yyyy-MM-dd"))
            self.calendar.setCurrentPage(*state['month'])
            self.all_dates.setChecked(start is None)
        self.sync_month(*state['month'])
        self.sort_by, self.direction = sort_by, direction
        self.table.horizontalHeader().setSortIndicator(SORT_FIELDS.index(sort_by),
            Qt.SortOrder.AscendingOrder if direction == 'asc' else Qt.SortOrder.DescendingOrder)
        self.page = offset // 50
        self.applied = tuple(state.get('applied', state['spec']))
        self.views.setCurrentIndex(state.get('view', 0))
        self.cards.restore_position(state.get('cards_position', 0))
        restore_table_identity(self.table, state["table"])
        self.dirty = True

    def show_detail(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.records):
            self.detail.clear()
            return
        record = self.records[index]
        self.detail.setPlainText(
            f"{record['market']} {record['code']} {record['name']}\n"
            f"停牌：{local_date(record['suspended_at'])}　复牌："
            f"{local_date(record['resumed_at']) if record['resumed_at'] else '来源未提供'}\n"
            f"来源说明：{record['source_note'] or '来源未提供'}\n"
            f"原因：{record['reason'] or '来源未提供'}")

    def render(self, result):
        self.records = result[:50]
        self.render_cards()
        rows(self.table, [[r['code'], r['name'], local_date(r['suspended_at']),
                          local_date(r['resumed_at']) if r['resumed_at'] else "来源未提供",
                          r['source_note'], r['reason']] for r in self.records],
             keys=[tuple(r[k] for k in ('market', 'code', 'suspended_at', 'resumed_at',
                                        'source_note', 'reason')) for r in self.records])
        if self.records and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(len(result) > 50)
        scope = self.applied[2] or "全部历史"
        self.status.setText(f"{scope} · 第 {self.page + 1} 页 · 本页 {len(self.records)} 条来源记录"
                            if result else "暂无匹配的已归档记录；可调整条件或查看采集进度。")
        self.show_detail()

    def render_coverage(self):
        day = self.applied[2]
        coverage = self.coverage or {}
        through = coverage.get('through', '')
        if self.coverage is None:
            message = '来源日历完整性尚未核实，当前结果可能不完整。'
        elif day is None:
            message = f"来源日期连续补查至 {through or '尚未开始'}；其后结果可能不完整。"
        elif coverage.get('from', '9999-12-31') <= day <= through:
            message = '该来源日期已完整核验并归档。'
        else:
            message = '该来源日期尚未完成补查；无结果不代表通达信当天没有记录。'
        self.coverage_status.setText(message)

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        self.tick_month()
        if self.coverage_future and self.coverage_future.done():
            future, self.coverage_future = self.coverage_future, None
            try:
                self.coverage = self.query_scope.result('coverage', future)
            except Exception:
                self.coverage = None
            self.render_coverage()
        if self.future and self.future.done():
            future, requested = self.future, self.query_spec
            self.future = self.query_spec = None
            if requested == self.spec():
                try:
                    self.render(self.query_scope.result("suspensions", future))
                except Exception as exc:
                    self.status.setText(self.query_scope.failure_message(
                        "suspensions", "停复牌查询失败", redact(exc, self.shell.cfg),
                        stale=bool(self.records)))
            else:
                self.query_scope.discard("suspensions", future)
        if self.isVisible() and self.dirty and not self.future:
            self.dirty = False
            self.query_spec = self.spec()
            self.coverage = None
            self.render_coverage()
            self.coverage_future = self.query_scope.invoke(
                'coverage', self.shell.runtime, 'suspensions.query', 'calendar_coverage')
            self.future = self.query_scope.invoke(
                "suspensions", self.shell.runtime, "suspensions.query", "list_events", *self.query_spec)


class SuspensionsUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.suspensions", "历史停复牌界面", provides=("ui.pages.suspensions",), autostart=True,
        description="通达信沪深 A 股历史停复牌来源记录浏览",
    )

    def create_pages(self):
        return (PageContribution(
            "suspensions", "历史停复牌", SuspensionsPage, "数据浏览", 3,
            "通达信沪深 A 股停复牌时间、来源说明及原因", catalogued=True, database_tables=("suspension_event",),
            category="交易可实现性", source="通达信", cache_policy="lru",
            management=NavigationTarget("collection", NavigationContext(task_id="tdx-suspensions"))),)
