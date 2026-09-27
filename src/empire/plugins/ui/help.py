from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor, QTextDocument, QTextFrameFormat, QTextTable
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
from empire.plugins.ui.plugin import UiPlugin

CATEGORIES = ("使用指南", "数据说明", "技术参考")


@dataclass(frozen=True)
class Article:
    category: str
    title: str
    body: str


def articles():
    contents = Path(__file__).with_name("storage_reference.md").read_text(encoding="utf-8")
    result = []
    for part in contents.split("<!-- topic:")[1:]:
        heading, body = part.split(" -->", 1)
        category, title = heading.split("|", 1)
        if category not in CATEGORIES:
            raise ValueError(f"未知文档分类：{category}")
        result.append(Article(category, title, body.strip()))
    return result


def topics():
    return {article.title: article.body for article in articles()}


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
        self.search.setPlaceholderText("搜索全部文档：股票、更新时间、重启…")
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
        self.index.setMinimumWidth(210)
        split.addWidget(self.index)
        self.browser = QTextBrowser()
        accessible(self.browser, "说明文档正文")
        self.browser.document().setDocumentMargin(24)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(DOCUMENT_STYLE)
        split.addWidget(self.browser)
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
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            self.browser.verticalScrollBar().setValue(0)
            query = self.search.text().strip()
            if query:
                self.browser.find(query)


class HelpUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.help", "说明文档界面", provides=("ui.pages.help",), autostart=True,
        description="说明文档界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("help", "说明文档", StorageHelpPage, "说明文档", 0,
                             "使用指南、重启恢复、配置保存与存储参考 · F1",
                             top_level=True, cache_policy="lru"),
        )
