"""Offline knowledge reader: grouped directory, search and reading history."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.desktop.theme import DOCUMENT_STYLE, windows_high_contrast
from empire.plugins.ui.common import accessible, bind_find
from empire.plugins.ui.help_content import CATEGORIES, articles, search_articles
from empire.plugins.ui.help_content import topics as topics
from empire.plugins.ui.help_reader import render_article
from empire.plugins.ui.plugin import UiPlugin


class StorageHelpPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.articles = articles()
        self.sections = {a.title: a.body for a in self.articles}
        self.by_title = {a.title: a for a in self.articles}
        self.current_topic = None
        self.positions, self.history, self.history_index = {}, [], -1
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        bar = QHBoxLayout()
        title = QLabel("说明文档")
        title.setObjectName("pageTitle")
        bar.addWidget(title)
        bar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索数据、问题、表名或 Redis 键")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.search.setMaximumWidth(480)
        accessible(self.search, "搜索说明文档", "多个关键词以空格分隔；Ctrl+F 聚焦。")
        bind_find(self, self.search)
        self.search.textChanged.connect(self.filter_topics)
        bar.addWidget(self.search)
        layout.addLayout(bar)
        split = QSplitter()
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        self.scope = QLabel("按目的和数据类型查找")
        self.scope.setObjectName("muted")
        side.addWidget(self.scope)
        self.index = QTreeWidget()
        self.index.setHeaderHidden(True)
        self.index.setIndentation(16)
        self.index.setUniformRowHeights(True)
        self.index.setTextElideMode(Qt.TextElideMode.ElideRight)
        if not windows_high_contrast():
            self.index.setStyleSheet("""
                QTreeWidget { border: 0; background: #f7f8fa; }
                QTreeWidget::item { padding: 6px 4px; }
                QTreeWidget::item:selected { background: #eaf1ff; color: #2456a6; }
                QTreeWidget::item:hover { background: #edf1f5; }
            """)
        accessible(self.index, "说明文档目录", "展开分类后选择主题；技术参考默认收起。")
        self.index.currentItemChanged.connect(self._selected)
        side.addWidget(self.index, 1)
        sidebar.setMinimumWidth(195)
        sidebar.setMaximumWidth(310)
        split.addWidget(sidebar)
        reader = QWidget()
        reading = QVBoxLayout(reader)
        reading.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.back = QPushButton("返回")
        self.back.clicked.connect(lambda: self.move_history(-1))
        tools.addWidget(self.back)
        self.forward = QPushButton("前进")
        self.forward.clicked.connect(lambda: self.move_history(1))
        tools.addWidget(self.forward)
        home = QPushButton("首页")
        home.clicked.connect(lambda: self.open_topic("开始使用"))
        tools.addWidget(home)
        tools.addStretch()
        self.chapters = QComboBox()
        accessible(self.chapters, "本页章节", "选择章节跳转到相应位置。")
        self.chapters.setMinimumWidth(140)
        self.chapters.setMaximumWidth(240)
        self.chapters.currentIndexChanged.connect(self.jump_to_chapter)
        tools.addWidget(self.chapters)
        reading.addLayout(tools)
        self.location = QLabel()
        self.location.setObjectName("muted")
        self.location.setWordWrap(True)
        reading.addWidget(self.location)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        reading.addWidget(self.summary)
        self.browser = QTextBrowser()
        accessible(self.browser, "说明文档正文")
        self.browser.document().setDocumentMargin(24)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(DOCUMENT_STYLE)
        self.browser.anchorClicked.connect(self.open_link)
        reading.addWidget(self.browser, 1)
        split.addWidget(reader)
        split.setSizes([250, 800])
        split.setChildrenCollapsible(False)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.filter_topics()
        self.open_topic("开始使用")

    def filter_topics(self):
        query = self.search.text().strip()
        self.index.blockSignals(True)
        self.index.clear()
        self.items = {}
        if query:
            matches = search_articles(self.articles, query)
            for article in matches:
                self.add_article(self.index, article)
            self.scope.setText(f"全部分类 · {len(matches)} 个结果")
        else:
            self.scope.setText("按目的和数据类型查找")
            for category in CATEGORIES:
                group = QTreeWidgetItem(self.index, [category])
                font = group.font(0)
                font.setBold(True)
                group.setFont(0, font)
                group.setExpanded(category in ("入门", "日常操作", "数据说明"))
                subgroups = {}
                for article in self.articles:
                    if article.category != category:
                        continue
                    parent = group
                    if article.group:
                        if article.group not in subgroups:
                            subgroups[article.group] = QTreeWidgetItem(group, [article.group])
                        parent = subgroups[article.group]
                    self.add_article(parent, article)
        self.index.blockSignals(False)
        if query and not self.items:
            self.remember_position()
            self.current_topic = None
            self.chapters.clear()
            self.location.clear()
            self.summary.clear()
            self.browser.setPlainText("没有匹配的说明。试试数据名称、操作名称或更短的关键词。")
        elif query:
            self.index.setCurrentItem(next(iter(self.items.values())))
        elif self.current_topic in self.items:
            self.select_item(self.current_topic)

    def add_article(self, parent, article):
        item = QTreeWidgetItem(parent, [article.title])
        item.setData(0, Qt.ItemDataRole.UserRole, article.title)
        item.setToolTip(0, f"{article.category} / {article.group or article.title}\n{article.summary}")
        self.items[article.title] = item

    def select_item(self, title):
        self.index.blockSignals(True)
        item = self.items[title]
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.index.setCurrentItem(item)
        self.index.scrollToItem(item)
        self.index.blockSignals(False)

    def _selected(self, item, previous=None):
        if item:
            title = item.data(0, Qt.ItemDataRole.UserRole)
            if title:
                self.show_topic(title)

    def remember_position(self):
        if self.current_topic:
            self.positions[self.current_topic] = self.browser.verticalScrollBar().value()

    def show_topic(self, title, *, track=True):
        if title not in self.by_title:
            return
        self.remember_position()
        if track and (self.history_index < 0 or self.history[self.history_index] != title):
            self.history = self.history[:self.history_index + 1] + [title]
            self.history = self.history[-50:]
            self.history_index = len(self.history) - 1
        self.current_topic = title
        article = self.by_title[title]
        self.location.setText(" / ".join(filter(None, (article.category, article.group, title))))
        self.summary.setText(article.summary)
        render_article(self.browser, self.chapters, article.body)
        self.browser.verticalScrollBar().setValue(self.positions.get(title, 0))
        query = self.search.text().strip()
        if query:
            self.browser.find(query.split()[0])
        if title in self.items:
            self.select_item(title)
        self.back.setEnabled(self.history_index > 0)
        self.forward.setEnabled(self.history_index < len(self.history) - 1)

    def open_topic(self, title):
        if title not in self.by_title:
            return
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.filter_topics()
        self.show_topic(title)

    def open_link(self, url):
        if url.scheme() == "help":
            self.open_topic(url.path())

    def move_history(self, direction):
        target = self.history_index + direction
        if 0 <= target < len(self.history):
            self.history_index = target
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.filter_topics()
            self.show_topic(self.history[target], track=False)

    def jump_to_chapter(self, index):
        position = self.chapters.itemData(index)
        if position is not None:
            cursor = QTextCursor(self.browser.document())
            cursor.setPosition(position)
            self.browser.setTextCursor(cursor)
            self.browser.ensureCursorVisible()

    def save_ui_state(self):
        self.remember_position()
        return {"search": self.search.text(), "current_topic": self.current_topic,
                "positions": dict(self.positions), "history": list(self.history),
                "history_index": self.history_index}

    def restore_ui_state(self, state):
        self.positions = dict(state["positions"])
        self.history, self.history_index = list(state["history"]), state["history_index"]
        self.current_topic = None
        self.search.blockSignals(True)
        self.search.setText(state["search"])
        self.search.blockSignals(False)
        self.filter_topics()
        if state["current_topic"]:
            self.show_topic(state["current_topic"], track=False)


class HelpUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.help", "说明文档界面", provides=("ui.pages.help",), autostart=True,
        description="离线说明文档与分组目录",
    )

    def create_pages(self):
        return (PageContribution("help", "说明文档", StorageHelpPage, "说明文档", 0,
                "操作指引、分类数据手册、故障处理与维护参考 · F1",
                top_level=True, cache_policy="lru"),)
