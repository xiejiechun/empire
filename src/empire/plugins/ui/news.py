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

from empire.core.config import redact
from empire.plugins.ui.collection import hint, rows, table
from empire.plugins.ui.home import local_date


class NewsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.offset = self.total = 0
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
        collect.clicked.connect(lambda: shell.navigate("collection"))
        heading.addWidget(collect)
        layout.addLayout(heading)
        layout.addWidget(hint("新浪 7×24 小时全球实时财经新闻直播 · 已归档历史 · 时间为北京时间"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索新闻标题或正文")
        self.search.setMaxLength(100)
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.search_changed)
        filters.addWidget(self.search, 1)
        self.important = QCheckBox("仅重点新闻")
        self.important.toggled.connect(self.search_changed)
        filters.addWidget(self.important)
        query = QPushButton("查询")
        query.clicked.connect(self.search_changed)
        filters.addWidget(query)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.status = hint("等待读取新闻……")
        layout.addWidget(self.status)
        self.table = table(["发布时间", "新闻标题", "分类", "重点"])
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
        return (self.search.text().strip(), self.offset, 50, self.important.isChecked())

    def search_changed(self):
        self.offset = 0
        self.reload()

    def move(self, step):
        self.offset = max(0, self.offset + step)
        self.reload()

    def reload(self):
        self.dirty = True
        self.tick()

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
        self.records, self.total = value["rows"], value["total"]
        self.table.blockSignals(True)
        rows(self.table, [[local_date(r["published_at"]), r["title"],
                          " / ".join(t["name"] for t in r["tags"]), "重点" if r["is_important"] else ""]
                         for r in self.records])
        if self.records:
            index = next((i for i, r in enumerate(self.records) if r["news_id"] == selected_id), 0)
            self.table.selectRow(index)
            for i, record in enumerate(self.records):
                self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, record["news_id"])
        self.table.blockSignals(False)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + 50 < self.total)
        self.status.setText(f"共 {self.total:,} 条 · 第 {self.offset // 50 + 1} 页 · 首页每 15 秒刷新已入库数据"
                            if self.total else "暂无匹配新闻。首次使用请到采集任务执行新浪财经新闻采集。")
        self.show_detail()

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, spec = self.future, self.query_spec
            self.future = self.query_spec = None
            if spec == self.spec():
                try:
                    self.render(future.result())
                except Exception as exc:
                    self.status.setText("新闻查询失败：" + redact(exc, self.shell.cfg))
            else:
                self.dirty = True
        if self.isVisible() and not self.future and (self.dirty or (self.offset == 0 and time.monotonic() - self.last_query >= 15)):
            self.query_spec = self.spec()
            self.dirty = False
            self.last_query = time.monotonic()
            try:
                self.future = self.shell.runtime.invoke("news.query", "list_news", *self.query_spec)
            except Exception as exc:
                self.status.setText("新闻查询服务未就绪：" + redact(exc, self.shell.cfg))
