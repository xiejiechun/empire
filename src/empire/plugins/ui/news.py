import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
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


class NewsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        from empire.plugins.ui.queries import QueryScope
        self.query_scope = QueryScope(self)
        self.page = self.total = 0
        self.cursors, self.anchor, self.next_cursor = [None], None, None
        self.records = []
        self.future = self.query_spec = None
        self.last_query = 0
        self.dirty = True
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("财经快讯")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        heading.addStretch()
        collect = QPushButton("管理采集计划")
        collect.clicked.connect(lambda: shell.navigate_management("news"))
        heading.addWidget(collect)
        layout.addLayout(heading)
        layout.addWidget(hint("新浪 7×24 小时全球实时财经新闻直播 · 已归档历史 · 时间为北京时间"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索新闻标题或正文")
        self.search.setMaxLength(100)
        self.search.setClearButtonEnabled(True)
        accessible(self.search, "搜索财经快讯", "输入标题或正文关键词；按 Ctrl+F 可回到此处。")
        bind_find(self, self.search)
        self.search.returnPressed.connect(self.search_changed)
        filters.addWidget(self.search, 1)
        self.important = QCheckBox("仅重点新闻")
        self.important.toggled.connect(self.search_changed)
        filters.addWidget(self.important)
        query = QPushButton("查询")
        query.clicked.connect(self.search_changed)
        filters.addWidget(query)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.status = hint("等待读取新闻……")
        self.status.setAccessibleName("财经快讯查询状态")
        layout.addWidget(self.status)
        self.table = table(["发布时间", "新闻标题", "分类", "重点"])
        self.table.setAccessibleName("财经快讯结果")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        navigation = QHBoxLayout()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.clicked.connect(lambda: self.move(-50))
        self.next.clicked.connect(lambda: self.move(50))
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        navigation.addWidget(self.previous)
        navigation.addWidget(self.next)
        navigation.addStretch()
        self.copy = QPushButton("复制正文")
        self.copy.clicked.connect(self.copy_content)
        self.open_source = QPushButton("打开来源")
        self.open_source.clicked.connect(self.open_url)
        navigation.addWidget(self.copy)
        navigation.addWidget(self.open_source)
        layout.addLayout(navigation)
        self.detail = QPlainTextEdit()
        accessible(self.detail, "财经快讯正文")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择一条新闻，查看完整正文、发布时间及来源链接。")
        self.detail.setMinimumHeight(180)
        self.detail.setMaximumHeight(280)
        layout.addWidget(self.detail)
        self.show_detail()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)

    def spec(self):
        return (self.search.text().strip(), 50, self.important.isChecked(),
                self.cursors[self.page], self.anchor, self.page == 0)

    def save_ui_state(self):
        return {"search": self.search.text(), "important": self.important.isChecked(),
                "page": self.page, "total": self.total, "cursors": list(self.cursors),
                "anchor": self.anchor, "next_cursor": self.next_cursor,
                "table": table_identity_state(self.table)}

    def restore_ui_state(self, state):
        self.search.setText(state["search"])
        self.important.blockSignals(True)
        self.important.setChecked(state["important"])
        self.important.blockSignals(False)
        self.page, self.total = state["page"], state["total"]
        self.cursors, self.anchor = list(state["cursors"]), state["anchor"]
        self.next_cursor = state["next_cursor"]
        restore_table_identity(self.table, state["table"])
        self.dirty = True

    def reset_paging(self):
        self.page, self.total = 0, 0
        self.cursors, self.anchor, self.next_cursor = [None], None, None

    def search_changed(self):
        self.reset_paging()
        self.reload()

    def move(self, step):
        if step > 0 and self.next_cursor:
            self.cursors = self.cursors[:self.page + 1] + [self.next_cursor]
            self.page += 1
        elif step < 0 and self.page:
            self.page -= 1
        self.reload()

    def reload(self):
        if self.future is not None:
            self.query_scope.cancel("news")
            self.future = None
        self.dirty = True
        self.tick()

    def refresh(self):
        if self.page == 0:
            self.anchor = None
        self.reload()

    def selected(self):
        index = self.table.currentRow()
        return self.records[index] if 0 <= index < len(self.records) else None

    def show_detail(self):
        record = self.selected()
        self.copy.setEnabled(bool(record))
        self.open_source.setEnabled(bool(record))
        content = (f"{record['title']}\n发布时间：{local_date(record['published_at'])}（北京时间）"
                   f"\n来源修订：{local_date(record['source_updated_at'])}\n\n{record['content']}"
                   f"\n\n来源：{record['url']}" if record else "")
        if self.detail.toPlainText() != content:
            self.detail.setPlainText(content)

    def copy_content(self):
        if record := self.selected():
            QApplication.clipboard().setText(record["content"])

    def open_url(self):
        if record := self.selected():
            url = QUrl(record["url"])
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)

    def render(self, value):
        selected = self.selected()
        selected_id = selected["news_id"] if selected else None
        self.records = value["rows"]
        if value["total"] is not None:
            self.total = value["total"]
        self.anchor, self.next_cursor = value["anchor"], value["next_cursor"]
        self.table.blockSignals(True)
        rows(self.table, [[local_date(r["published_at"]), r["title"],
                          " / ".join(t["name"] for t in r["tags"]), "重点" if r["is_important"] else ""]
                         for r in self.records], keys=[r["news_id"] for r in self.records])
        if self.records and selected_id is not None:
            index = next((i for i, r in enumerate(self.records) if r["news_id"] == selected_id), 0)
            self.table.selectRow(index)
        elif self.records and self.table.currentRow() < 0:
            self.table.selectRow(0)
            for i, record in enumerate(self.records):
                self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, record["news_id"])
        self.table.blockSignals(False)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(bool(self.next_cursor))
        self.status.setText(f"共 {self.total:,} 条 · 第 {self.page + 1} 页 · 首页每 15 秒刷新已入库数据"
                            if self.total else "暂无匹配新闻。首次使用请到采集任务执行新浪财经新闻采集。")
        self.show_detail()

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, spec = self.future, self.query_spec
            self.future = self.query_spec = None
            if spec == self.spec():
                try:
                    self.render(self.query_scope.result("news", future))
                except Exception as exc:
                    self.status.setText(self.query_scope.failure_message(
                        "news", "新闻查询失败", redact(exc, self.shell.cfg),
                        stale=bool(self.records),
                    ))
            else:
                self.query_scope.discard("news", future)
                self.dirty = True
        home_refresh = self.page == 0 and time.monotonic() - self.last_query >= 15
        if self.isVisible() and not self.future and (self.dirty or home_refresh):
            if home_refresh:
                self.anchor = None
            self.query_spec = self.spec()
            self.dirty = False
            self.last_query = time.monotonic()
            self.future = self.query_scope.invoke(
                "news", self.shell.runtime, "news.query", "list_news", *self.query_spec)


class NewsUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.news", "财经快讯界面", provides=("ui.pages.news",), autostart=True,
        description="财经快讯界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("news", "财经快讯", NewsPage, "数据浏览", 1,
                             "新浪 7×24 新闻、搜索与重点筛选", catalogued=True,
                             category="资讯", source="新浪财经", cache_policy="lru",
                             management=NavigationTarget(
                                 "collection", NavigationContext(task_id="sina-news"))),
        )
