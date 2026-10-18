"""Markdown rendering and bounded chapter locations for the offline reader."""
from PySide6.QtGui import QColor, QTextCursor, QTextDocument, QTextFrameFormat, QTextTable


def render_article(browser, chapters, body):
    browser.document().setMarkdown(body,
        QTextDocument.MarkdownFeature.MarkdownDialectGitHub |
        QTextDocument.MarkdownFeature.MarkdownNoHTML)
    chapters.blockSignals(True)
    chapters.clear()
    chapters.addItem("本页章节", 0)
    block = browser.document().begin()
    while block.isValid():
        cursor = QTextCursor(block)
        if cursor.currentTable() is None:
            style = block.blockFormat()
            heading = style.headingLevel()
            style.setTopMargin(18 if heading == 2 else 0)
            style.setBottomMargin(10 if heading else 8)
            style.setLineHeight(145, 1)
            cursor.setBlockFormat(style)
            if heading == 2:
                chapters.addItem(block.text(), block.position())
        block = block.next()
    for frame in browser.document().rootFrame().childFrames():
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
                style = cell.format()
                style.setBackground(QColor("#f7f8fa"))
                cell.setFormat(style)
    chapters.blockSignals(False)
    browser.moveCursor(QTextCursor.MoveOperation.Start)
    browser.verticalScrollBar().setValue(0)
