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
    QTabWidget,
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
from empire.plugins.ui.preview_cards import CardReader, card, text


class NewsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        from empire.plugins.ui.queries import QueryScope
        self.query_scope = QueryScope(self)
        self.page = self.total = 0
        self.cursors, self.anchor, self.next_cursor = [None], None, None
        self.records = []
        self.applied = ('', False, '', '')
        self.expanded = set()
        self.latest_future = None
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
        dates = QHBoxLayout()
        self.start, self.end = QLineEdit(), QLineEdit()
        for field, label in ((self.start, '开始日期'), (self.end, '截止日期')):
            field.setPlaceholderText(label + ' YYYY-MM-DD；留空不限')
            accessible(field, '新闻' + label)
            field.returnPressed.connect(self.search_changed)
            dates.addWidget(field)
        self.update_button = QPushButton('查看最新')
        self.update_button.clicked.connect(self.show_latest)
        dates.addWidget(self.update_button)
        layout.addLayout(dates)
        self.status = hint("等待读取新闻……")
        self.status.setAccessibleName("财经快讯查询状态")
        layout.addWidget(self.status)
        self.table = table(["发布时间", "新闻标题", "分类", "重点"])
        self.table.setAccessibleName("财经快讯结果")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.views = QTabWidget()
        self.feed = CardReader('财经快讯阅读流')
        self.feed.selected.connect(self.expand_news)
        self.views.addTab(self.feed, '连续阅读')
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.addWidget(self.table, 1)
        self.views.addTab(detail_page, '检索明细')
        layout.addWidget(self.views, 1)
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
        self.selected_note = hint('尚未选择新闻。')
        layout.addWidget(self.selected_note)
        self.detail = QPlainTextEdit()
        accessible(self.detail, "财经快讯正文")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择一条新闻，查看完整正文、发布时间及来源链接。")
        self.detail.setMinimumHeight(180)
        detail_layout.addWidget(self.detail, 1)
        self.show_detail()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)

    def spec(self):
        search, important, start, end = self.applied
        return (search, 50, important, self.cursors[self.page], self.anchor, self.page == 0, start, end)

    def save_ui_state(self):
        return {"search": self.search.text(), "important": self.important.isChecked(),
                "page": self.page, "total": self.total, "cursors": list(self.cursors),
                "anchor": self.anchor, "next_cursor": self.next_cursor,
                "table": table_identity_state(self.table), 'start': self.start.text(), 'end': self.end.text(),
                'applied': self.applied, 'view': self.views.currentIndex(), 'expanded': list(self.expanded),
                'position': self.feed.save_position()}

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
        self.start.setText(state.get('start', ''))
        self.end.setText(state.get('end', ''))
        self.applied = tuple(state.get('applied', ('', False, '', '')))
        self.views.setCurrentIndex(state.get('view', 0))
        self.expanded = set(state.get('expanded', []))
        self.feed_position = state.get('position', 0)

    def reset_paging(self):
        self.page, self.total = 0, 0
        self.cursors, self.anchor, self.next_cursor = [None], None, None

    def search_changed(self):
        self.applied = (self.search.text().strip(), self.important.isChecked(),
                        self.start.text().strip(), self.end.text().strip())
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
        self.update_button.setText('查看最新')

    def show_latest(self):
        self.reset_paging()
        self.refresh()

    def selected(self):
        index = self.table.currentRow()
        return self.records[index] if 0 <= index < len(self.records) else None

    def show_detail(self):
        record = self.selected()
        self.copy.setEnabled(bool(record))
        self.open_source.setEnabled(bool(record and record.get('url')))
        self.selected_note.setText('当前所选：' + local_date(record['published_at']) + ' · '
            + (record['title'] or '来源未提供标题') if record else '尚未选择新闻。')
        content = (f"{record['title']}\n发布时间：{local_date(record['published_at'])}（北京时间）"
                   f"\n来源修订：{local_date(record['source_updated_at'])}\n\n{record['content']}"
                   f"\n\n来源：{record['url']}" if record else "")
        if self.detail.toPlainText() != content:
            self.detail.setPlainText(content)

    def expand_news(self, index):
        if not 0 <= index < len(self.records):
            return
        ident = self.records[index]['news_id']
        if ident in self.expanded:
            self.expanded.remove(ident)
        else:
            self.expanded.add(ident)
        self.table.selectRow(index)
        self.render_feed()

    def render_feed(self):
        previous, body = None, []
        for i, record in enumerate(self.records):
            day = record['published_at'][:10]
            if day != previous:
                body.append(f'<h2>{text(day)} · 北京时间</h2>')
                previous = day
            expanded = record['news_id'] in self.expanded
            content = record['content'] if expanded else record['content'][:250]
            body.append(card(record['title'] or '来源未提供标题', '<p>' + text(content) + '</p>'
                + f'<a href="record:{i}">{"收起正文" if expanded else "展开正文 / 选择记录"}</a>',
                record['published_at'][11:19] + (' · 重点' if record['is_important'] else '')))
        self.feed.present(''.join(body) or '<p>暂无匹配的已归档新闻。</p>', identity=(self.applied, self.page))
        if hasattr(self, 'feed_position'):
            self.feed.verticalScrollBar().setValue(self.feed_position)
            del self.feed_position

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
        self.status.setText(f"共 {self.total:,} 条 · 第 {self.page + 1} 页 · 已应用关键词 {self.applied[0] or '不限'} · 自动检查新消息，点击查看最新"
                            if self.total else "当前条件下没有已归档新闻；可调整关键词、日期或检查采集状态。")
        self.show_detail()
        self.render_feed()

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
        if self.latest_future and self.latest_future.done():
            future, self.latest_future = self.latest_future, None
            try:
                latest = self.query_scope.result('news-latest', future)
                if latest and self.anchor and (latest['published_at'], latest['news_id']) > (self.anchor['published_at'], self.anchor['news_id']):
                    self.update_button.setText('有新消息 · 点击查看')
            except Exception:
                self.update_button.setToolTip('新消息检查暂不可用；当前阅读内容保留')
        if self.isVisible() and not self.latest_future and time.monotonic()-self.last_query >= 15 and not self.dirty:
            self.last_query = time.monotonic()
            self.latest_future = self.query_scope.invoke('news-latest', self.shell.runtime, 'news.query', 'latest')
        if self.isVisible() and not self.future and self.dirty:
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
                             "新浪 7×24 新闻、搜索与重点筛选", catalogued=True, database_tables=("finance_news",),
                             category="资讯", source="新浪财经", cache_policy="lru",
                             management=NavigationTarget(
                                 "collection", NavigationContext(task_id="sina-news"))),
        )
