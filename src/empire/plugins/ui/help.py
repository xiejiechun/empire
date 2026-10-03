
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor, QTextDocument, QTextFrameFormat, QTextTable
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.desktop.theme import DOCUMENT_STYLE
from empire.plugins.ui.common import accessible, bind_find
from empire.plugins.ui.help_content import CATEGORIES, articles
from empire.plugins.ui.help_content import topics as topics
from empire.plugins.ui.plugin import UiPlugin


class StorageHelpPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.articles = articles()
        self.sections = {article.title: article.body for article in self.articles}
        self.categories = {article.title: article.category for article in self.articles}
        self.remembered = {}
        self.current_topic = None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        bar = QHBoxLayout()
        title = QLabel("说明文档")
        title.setObjectName("pageTitle")
        bar.addWidget(title)
        bar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索操作、数据或问题：采集、财报、重启…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.setMaximumWidth(420)
        accessible(self.search, "搜索说明文档", "输入主题或字段名称；按 Ctrl+F 可回到此处。")
        bind_find(self, self.search)
        self.search.textChanged.connect(self.filter_topics)
        bar.addWidget(self.search)
        layout.addLayout(bar)
        self.tabs = QTabBar()
        accessible(self.tabs, "说明文档分类")
        self.tabs.setExpanding(False)
        for category in CATEGORIES:
            self.tabs.addTab(category)
        layout.addWidget(self.tabs)
        self.scope = QLabel()
        self.scope.setObjectName("muted")
        layout.addWidget(self.scope)
        split = QSplitter()
        self.index = QListWidget()
        accessible(self.index, "说明文档主题列表", "使用方向键选择主题。")
        self.index.currentItemChanged.connect(self._selected)
        self.index.setMinimumWidth(180)
        self.index.setMaximumWidth(300)
        split.addWidget(self.index)
        reader = QWidget()
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        home = QPushButton("入门首页")
        home.clicked.connect(lambda: self.open_topic("开始使用"))
        tools.addWidget(home)
        self.location = QLabel()
        self.location.setObjectName("muted")
        tools.addWidget(self.location, 1)
        self.chapters = QComboBox()
        accessible(self.chapters, "本页章节", "选择章节跳转到文章相应位置。")
        self.chapters.setMinimumWidth(160)
        self.chapters.setMaximumWidth(240)
        self.chapters.currentIndexChanged.connect(self.jump_to_chapter)
        tools.addWidget(self.chapters)
        reader_layout.addLayout(tools)
        self.browser = QTextBrowser()
        accessible(self.browser, "说明文档正文")
        self.browser.document().setDocumentMargin(24)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(DOCUMENT_STYLE)
        self.browser.anchorClicked.connect(self.open_link)
        reader_layout.addWidget(self.browser, 1)
        split.addWidget(reader)
        split.setSizes([230, 760])
        split.setChildrenCollapsible(False)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.tabs.currentChanged.connect(self.change_category)
        self.filter_topics()

    def change_category(self, index):
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.filter_topics()

    def save_ui_state(self):
        return {"search": self.search.text(), "tab": self.tabs.currentIndex(),
                "current_topic": self.current_topic, "remembered": dict(self.remembered),
                "scroll": self.browser.verticalScrollBar().value()}

    def restore_ui_state(self, state):
        self.remembered = dict(state["remembered"])
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(state["tab"])
        self.tabs.blockSignals(False)
        self.search.blockSignals(True)
        self.search.setText(state["search"])
        self.search.blockSignals(False)
        self.current_topic = state["current_topic"]
        self.filter_topics()
        if self.current_topic:
            self.show_topic(self.current_topic)
        self.browser.verticalScrollBar().setValue(state["scroll"])

    def filter_topics(self):
        category = CATEGORIES[self.tabs.currentIndex()]
        query = self.search.text().strip().casefold()
        matches = [article for article in self.articles
                   if (query in (article.title + article.body).casefold()
                       if query else article.category == category)]
        selected = self.current_topic if query else self.remembered.get(category)
        self.index.blockSignals(True)
        self.index.clear()
        for article in matches:
            item = QListWidgetItem(article.title)
            item.setData(Qt.ItemDataRole.UserRole, article.title)
            item.setToolTip(f"{article.category} / {article.title}")
            self.index.addItem(item)
        self.index.blockSignals(False)
        self.scope.setText(f"全部分类 · 找到 {len(matches)} 篇文档" if query else
            f"{category} · {len(matches)} 篇文档")
        if matches:
            titles = [article.title for article in matches]
            self.index.setCurrentRow(titles.index(selected) if selected in titles else 0)
        else:
            self.current_topic = None
            self.chapters.clear()
            self.location.clear()
            self.browser.setPlainText("没有匹配的说明，试试字段名或更短的关键词。")

    def _selected(self, item, previous=None):
        if item:
            self.show_topic(item.data(Qt.ItemDataRole.UserRole))

    def show_topic(self, title):
        if title in self.sections:
            self.current_topic = title
            category = self.categories[title]
            self.remembered[category] = title
            if self.search.text().strip():
                self.scope.setText(f"全部分类 · 找到 {self.index.count()} 篇文档 · 当前：{category}")
            self.location.setText(f"{category} / {title}")
            # Literal angle-bracket placeholders must not be consumed as HTML tags.
            self.browser.document().setMarkdown(self.sections[title],
                QTextDocument.MarkdownFeature.MarkdownDialectGitHub |
                QTextDocument.MarkdownFeature.MarkdownNoHTML)
            block = self.browser.document().begin()
            while block.isValid():
                cursor = QTextCursor(block)
                if cursor.currentTable() is None:
                    style = block.blockFormat()
                    heading = style.headingLevel()
                    style.setTopMargin(18 if heading == 2 else 0)
                    style.setBottomMargin(10 if heading else 8)
                    style.setLineHeight(140, 1)  # ProportionalHeight, in percent.
                    cursor.setBlockFormat(style)
                block = block.next()
            # Qt's Markdown importer does not apply CSS table padding.
            for frame in self.browser.document().rootFrame().childFrames():
                if isinstance(frame, QTextTable):
                    style = frame.format()
                    style.setBorder(1)
                    style.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                    style.setBorderBrush(QColor("#e3e7ed"))
                    style.setCellPadding(7)
                    style.setCellSpacing(0)
                    frame.setFormat(style)
                    for column in range(frame.columns()):
                        cell = frame.cellAt(0, column)
                        cell_style = cell.format()
                        cell_style.setBackground(QColor("#f7f8fa"))
                        cell.setFormat(cell_style)
            self.chapters.blockSignals(True)
            self.chapters.clear()
            self.chapters.addItem("本页章节", 0)
            block = self.browser.document().begin()
            while block.isValid():
                if block.blockFormat().headingLevel() == 2:
                    self.chapters.addItem(block.text(), block.position())
                block = block.next()
            self.chapters.blockSignals(False)
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            self.browser.verticalScrollBar().setValue(0)
            query = self.search.text().strip()
            if query:
                self.browser.find(query)


    def jump_to_chapter(self, index):
        position = self.chapters.itemData(index)
        if position is not None:
            cursor = QTextCursor(self.browser.document())
            cursor.setPosition(position)
            self.browser.setTextCursor(cursor)
            self.browser.ensureCursorVisible()

    def open_link(self, url):
        if url.scheme() == "help":
            self.open_topic(url.path())

    def open_topic(self, title):
        if title not in self.sections:
            return
        category = self.categories[title]
        self.remembered[category] = title
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(CATEGORIES.index(category))
        self.tabs.blockSignals(False)
        self.filter_topics()


class HelpUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.help", "说明文档界面", provides=("ui.pages.help",), autostart=True,
        description="说明文档界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("help", "说明文档", StorageHelpPage, "说明文档", 0,
                             "入门、操作、数据、故障处理与技术参考 · F1",
                             top_level=True, cache_policy="lru"),
        )
