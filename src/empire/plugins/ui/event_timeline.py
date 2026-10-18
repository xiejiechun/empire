"""Source-event timeline presentation; no inferred lifecycle intervals."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from empire.plugins.ui.preview_cards import CardReader, card, fields, text
from empire.plugins.ui.preview_navigation import navigate_security


class EventTimeline(QWidget):
    def __init__(self, table, title, *, reason=False):
        super().__init__()
        self.table, self.title, self.reason = table, title, reason
        self.records, self.identity = [], None
        self.expanded = set()
        self.links = []
        self.selection = QLabel('选择事件后可查看该证券的其他数据。')
        self.selection.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self.update_selection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.views = QTabWidget()
        self.reader = CardReader(title + '时间线')
        self.reader.selected.connect(self.expand)
        self.views.addTab(self.reader, '事件时间线')
        self.views.addTab(table, '来源明细')
        layout.addWidget(self.views)

    def add_links(self, shell, targets):
        self.layout().addWidget(self.selection)
        bar = QHBoxLayout()
        for label, target in targets:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, page=target: self.open_record(shell, page))
            button.setEnabled(False)
            self.links.append(button)
            bar.addWidget(button)
        self.layout().addLayout(bar)

    def update_selection(self):
        index = self.table.currentRow()
        valid = 0 <= index < len(self.records)
        for button in self.links:
            button.setEnabled(valid)
        self.selection.setText('所选事件：' + self.records[index]['unified_code'] + ' · '
            + self.records[index]['event_date'] if valid else '选择事件后可查看该证券的其他数据。')

    def open_record(self, shell, page):
        index = self.table.currentRow()
        if 0 <= index < len(self.records):
            navigate_security(shell, page, self.records[index]['unified_code'])

    def expand(self, index):
        if not 0 <= index < len(self.records):
            return
        key = self.records[index]['record_key']
        self.expanded.symmetric_difference_update({key})
        self.table.selectRow(index)
        self.render(self.records, self.identity)

    def render(self, records, identity=None):
        self.records, self.identity = records, identity
        parts, year = [], None
        for i, record in enumerate(records):
            stamp = record['event_date']
            if stamp[:4] != year:
                parts.append(f'<h2>{text(stamp[:4])}年 · {text(self.title)}</h2>')
                year = stamp[:4]
            body = '<p><b>' + text(record.get('old_name')) + ' → ' + text(record.get('new_name')) + '</b></p>'
            if self.reason:
                body += '<p>原因：' + text(record.get('reason')) + '</p>'
            key = record['record_key']
            if key in self.expanded:
                body += fields([('来源出现次数', record.get('source_occurrences')),
                    ('证监会行业（无历史归属日期）', record.get('csrc_industry')),
                    ('通达信行业（无历史归属日期）', record.get('tdx_industry')),
                    ('来源记录身份', key)])
            body += f'<p><a href="record:{i}">{"收起" if key in self.expanded else "更多来源信息"}</a></p>'
            parts.append(card(record['unified_code'], body, stamp + ' · 来源事件日期'))
        self.reader.present(''.join(parts) or '<p>暂无匹配的已归档事件；不能据此证明没有事件。</p>', identity=identity)
        self.update_selection()
