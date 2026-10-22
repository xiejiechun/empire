"""Lazy SQL browser; source and optional observation data stay visibly distinct."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.hot_list.contract import PROJECT
from empire.features.hot_list.presentation import STATUS, render
from empire.plugins.ui.common import (
    accessible,
    hint,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class HotListPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.applied, self.after, self.next_cursor, self.history = ("", "", ""), None, None, []
        self.future = self.detail_future = self.requested = self.selected = (
            self.detail_requested
        ) = None
        self.data, self.dirty = [], True
        layout = QVBoxLayout(self)
        title = QLabel("个股龙虎榜（通达信）")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(
            hint(
                "按证券和日期查看全部已归档上榜原因及买卖席位；单日与多日榜不重复相加；缺失不填零。"
            )
        )
        bar = QHBoxLayout()
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label in (
            (self.code, "证券代码或前缀"),
            (self.start, "开始 YYYY-MM-DD"),
            (self.end, "截止 YYYY-MM-DD"),
        ):
            accessible(field, "龙虎榜" + label)
            field.setPlaceholderText(label)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        find, manage = QPushButton("查询 / 刷新"), QPushButton("管理采集")
        find.clicked.connect(self.find)
        manage.clicked.connect(
            lambda: shell.navigate("collection", NavigationContext(task_id=PROJECT))
        )
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint("正在读取已归档日期…")
        layout.addWidget(self.status)
        self.table = table(["证券", "榜单日期", "来源目录", "详情状态", "原因条数", "席位条数"])
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.previous, self.next = QPushButton("上一页"), QPushButton("下一页")
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        buttons.addWidget(self.previous)
        buttons.addWidget(self.next)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(False)
        layout.addWidget(self.reader, 2)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)

    def find(self):
        self.applied = tuple(f.text().strip() for f in (self.code, self.start, self.end))
        self.after, self.history, self.next_cursor, self.dirty = None, [], None, True
        self.selected = None
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.reader.clear()

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def select(self):
        index = self.table.currentRow()
        self.selected = (
            (self.data[index]["unified_code"], self.data[index]["list_date"])
            if 0 <= index < len(self.data)
            else None
        )

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.scope.close()
            self.timer.stop()
            return
        if not self.isVisible():
            return
        spec = (*self.applied, self.after)
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != spec:
                self.scope.discard("days", future)
            else:
                try:
                    result = self.scope.result("days", future)
                    self.data, self.next_cursor = result["rows"], result["next"]
                    rows(
                        self.table,
                        [
                            [
                                r["unified_code"],
                                r["list_date"],
                                "在目录" if r["directory_listed"] else "已退出目录",
                                STATUS[r["detail_status"]],
                                r["reason_count"],
                                r["seat_count"],
                            ]
                            for r in self.data
                        ],
                        keys=[(r["unified_code"], r["list_date"]) for r in self.data],
                    )
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(
                        f"本页{len(self.data)}个日期，每页最多200；选择一行查看原因与席位。"
                    )
                    self.detail_requested = None
                    self.select()
                    if not self.data:
                        self.reader.setPlainText(
                            "此范围没有已归档日期；未采集与来源无记录须分别核查。"
                        )
                except Exception as exc:
                    self.status.setText(
                        self.scope.failure_message(
                            "days", "查询失败", redact(exc, self.shell.cfg), stale=bool(self.data)
                        )
                    )
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            if self.detail_requested != self.selected:
                self.scope.discard("detail", future)
                self.detail_requested = None
            else:
                try:
                    self.reader.setHtml(render(self.scope.result("detail", future)))
                except Exception as exc:
                    self.reader.setPlainText("详情查询失败：" + redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, spec
            self.future = self.scope.invoke(
                "days", self.shell.runtime, "hot_list.query", "browse", *spec
            )
        if (
            self.isVisible()
            and self.selected
            and self.selected != self.detail_requested
            and not self.detail_future
        ):
            self.detail_requested = self.selected
            self.detail_future = self.scope.invoke(
                "detail", self.shell.runtime, "hot_list.query", "detail", *self.selected
            )

    def apply_navigation_context(self, context):
        self.code.setText(context.unified_code)
        self.start.setText(context.start)
        self.end.setText(context.end)
        self.find()

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future = self.detail_future = self.detail_requested = None
        self.dirty = True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(500)

    def save_ui_state(self):
        return dict(
            draft=[f.text() for f in (self.code, self.start, self.end)],
            applied=self.applied,
            after=self.after,
            history=self.history,
            table=table_identity_state(self.table),
        )

    def restore_ui_state(self, state):
        for field, value in zip((self.code, self.start, self.end), state["draft"], strict=True):
            field.setText(value)
        self.applied, self.after, self.history = (
            tuple(state["applied"]),
            state["after"],
            list(state["history"]),
        )
        restore_table_identity(self.table, state["table"])
        self.dirty = True


class HotListUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.hot_list",
        "龙虎榜浏览",
        provides=("ui.pages.hot_list",),
        description="按需创建日期与席位浏览",
    )

    def create_pages(self):
        return (
            PageContribution(
                "hot_list",
                "个股龙虎榜",
                HotListPage,
                "数据浏览",
                50,
                "全部可得历史、原因与席位；来源缺失单独呈现",
                database_tables=("hot_list_day", "hot_list_reason", "hot_list_seat"),
                catalogued=True,
                category="交易事件",
                source="通达信",
                cache_policy="lru",
                management=NavigationTarget("collection", NavigationContext(task_id=PROJECT)),
            ),
        )
