"""Accessible text cards with stable identity and safe application links."""
from html import escape

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QTextBrowser


def text(value):
    return escape(str(value if value is not None and value != '' else '—')).replace('\n', '<br>')


def fields(items):
    return '<table cellspacing="8" width="100%">' + ''.join(
        f'<tr><td width="28%"><b>{text(k)}</b></td><td>{text(v)}</td></tr>'
        for k, v in items) + '</table>'


def card(title, body, subtitle=''):
    return f'<h2 style="font-size:16px;margin-bottom:6px">{text(title)}</h2><p style="color:#536273">{text(subtitle)}</p>{body}<hr>'


class CardReader(QTextBrowser):
    selected = Signal(int)

    def __init__(self, name='数据阅读区', parent=None):
        super().__init__(parent)
        self.setAccessibleName(name)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._link)
        self.signature = None
        self.setMinimumHeight(180)

    def _link(self, url):
        if url.scheme() == 'record' and url.path().isdigit():
            self.selected.emit(int(url.path()))

    def present(self, html, *, identity=None):
        signature = identity, html
        if signature == self.signature:
            return
        bar = self.verticalScrollBar()
        previous = bar.value() if self.signature and identity == self.signature[0] else 0
        self.signature = signature
        previous = getattr(self, '_restored_position', previous)
        if hasattr(self, '_restored_position'):
            del self._restored_position
        self.setHtml('<html><body style="font-family:Microsoft YaHei;font-size:14px;line-height:150%;">'
                     + html + '</body></html>')
        bar.setValue(previous)
        QTimer.singleShot(0, lambda: bar.setValue(previous) if self.signature == signature else None)

    def save_position(self):
        return self.verticalScrollBar().value()

    def restore_position(self, position):
        self._restored_position = max(0, int(position))


def event_cards(records, title, subtitle, summary):
    if not records:
        return '<p>当前条件下没有已归档记录；不能据此认定来源无事件。</p>'
    return ''.join(card(title(r), summary(r) + f'<p><a href="record:{i}">查看完整记录</a></p>',
                        subtitle(r)) for i, r in enumerate(records))
