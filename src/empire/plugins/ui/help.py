from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def topics():
    contents = Path(__file__).with_name("storage_reference.md").read_text(encoding="utf-8")
    result = {}
    for part in contents.split("<!-- topic:")[1:]:
        title, body = part.split(" -->", 1)
        result[title] = body.strip()
    return result


class StorageHelpPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.sections = topics()
        layout = QVBoxLayout(self)
        title = QLabel("说明文档")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Redis 键、MySQL 表与字段、配置参数及数据保留规则。支持离线查看。"))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文档，如 history、snapshot_id、归档、水位")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_topics)
        bar.addWidget(self.search)
        layout.addLayout(bar)
        split = QSplitter()
        self.index = QListWidget()
        self.index.currentTextChanged.connect(self.show_topic)
        split.addWidget(self.index)
        self.browser = QTextBrowser()
        self.browser.document().setDocumentMargin(14)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(
            "table {border-collapse:collapse;} td, th {border:1px solid #344c6b;padding:8px;} "
            "th {background:#1a2a42;} h1 {font-size:20px;} h2 {font-size:16px;} p {line-height:150%;}")
        split.addWidget(self.browser)
        split.setSizes([200, 780])
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.filter_topics()

    def filter_topics(self):
        selected = self.index.currentItem().text() if self.index.currentItem() else None
        query = self.search.text().strip().casefold()
        matches = [title for title, body in self.sections.items() if query in (title + body).casefold()]
        self.index.clear()
        self.index.addItems(matches)
        if matches:
            self.index.setCurrentRow(matches.index(selected) if selected in matches else 0)
        else:
            self.browser.setPlainText("没有匹配的说明，试试字段名或更短的关键词。")

    def show_topic(self, title):
        if title in self.sections:
            self.browser.setMarkdown(self.sections[title])
            query = self.search.text().strip()
            if query:
                self.browser.find(query)
