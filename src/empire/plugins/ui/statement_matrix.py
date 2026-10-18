"""Offline source-inspired presentation; every archived field remains visible."""
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QTableWidgetItem, QWidget

from empire.plugins.datasets.financial_quality import quality_issues
from empire.plugins.ui.common import table


@lru_cache(maxsize=1)
def layouts():
    return json.loads(Path(__file__).with_name('statement_layouts.json').read_text(encoding='utf-8'))


def subject_layout(kind, records):
    fields = {key for row in records for key in row['fields']}
    if not fields:
        return []
    def score(layout):
        keys = {x[0] for x in layout if x[3]}
        return len(keys & fields) / len(keys | fields)
    reference = max(layouts()[kind], key=score)
    result, headings, used = [], [], set()
    for name, indent, bold, numeric in reference:
        if not numeric:
            headings.append((name, 0 if name.startswith('报表') else 1, True, False))
        elif name in fields and name not in used:
            result.extend(headings)
            headings = []
            result.append((name, indent + 1, bold, True))
            used.add(name)
    missing = sorted(fields - used)
    if missing:
        result.append(('其他来源科目（未归类）', 0, True, False))
        result.extend((name, 2, False, True) for name in missing)
    return result


def format_amount(value, divisor):
    if value is None:
        return '—'
    amount = Decimal(value['value']) / Decimal(divisor)
    if divisor == 1:
        return format(amount, ',f')
    return format(amount, ',.2f')


class StatementMatrix(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.subjects, self.values = table(['科目 / 年度']), table([])
        self.subjects.setFixedWidth(330)
        self.subjects.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.subjects.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.values.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.values.horizontalHeader().setDefaultSectionSize(145)
        for widget in (self.subjects, self.values):
            widget.horizontalHeader().setFixedHeight(48)
            widget.setSelectionBehavior(widget.SelectionBehavior.SelectItems)
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.subjects.horizontalScrollBar().setEnabled(False)
        self.subjects.verticalScrollBar().valueChanged.connect(self.values.verticalScrollBar().setValue)
        self.values.verticalScrollBar().valueChanged.connect(self.subjects.verticalScrollBar().setValue)
        layout.addWidget(self.subjects)
        layout.addWidget(self.values, 1)
        self.entries, self.reports = [], []
        self.collapsed, self.search = set(), ''
        self.subjects.itemDoubleClicked.connect(self.toggle_group)

    def toggle_group(self, item):
        entry = self.entries[item.row()]
        if not entry[3]:
            self.collapsed.symmetric_difference_update({entry[0]})
            self.search_subjects(self.search)

    def search_subjects(self, query):
        self.search = query
        parents, hidden_level = [], None
        visible = set()
        for i, (name, level, _, numeric) in enumerate(self.entries):
            if not numeric:
                parents = [(index, depth) for index, depth in parents if depth < level] + [(i, level)]
                if hidden_level is not None and level <= hidden_level:
                    hidden_level = None
                if name in self.collapsed and not query:
                    hidden_level = level
                visible.add(i)
            elif (query.casefold() in name.casefold() if query else hidden_level is None):
                visible.add(i)
                visible.update(index for index, _ in parents)
        if query:
            visible = {i for i in visible if self.entries[i][3]} | {index for i in visible if self.entries[i][3]
                for index in self._ancestors(i)}
        for i in range(len(self.entries)):
            self.subjects.setRowHidden(i, i not in visible)
            self.values.setRowHidden(i, i not in visible)

    def _ancestors(self, index):
        level = self.entries[index][1]
        result = []
        for i in range(index-1, -1, -1):
            if not self.entries[i][3] and self.entries[i][1] < level:
                result.append(i)
                level = self.entries[i][1]
        return result

    def resizeEvent(self, event):
        self.subjects.setFixedWidth(max(180, min(330, self.width()*38//100)))
        super().resizeEvent(event)

    def render(self, kind, records, annual=False, divisor=10000):
        blocker = QSignalBlocker(self.values)
        self.kind = kind
        scroll = self.values.verticalScrollBar().value()
        self.reports = sorted((r for r in records if not annual or r['report_date'].endswith('-12-31')),
                              key=lambda r: r['report_date'], reverse=True)
        self.entries = subject_layout(kind, records)
        self.values.setColumnCount(len(self.reports))
        self.values.setHorizontalHeaderLabels([
            r['report_date'][:4] + '\n' + r['report_date'][5:] +
            (' ⚠' if quality_issues(kind, r) else '') for r in self.reports])
        for col, report in enumerate(self.reports):
            self.values.horizontalHeaderItem(col).setToolTip('\n'.join(
                [report['report_date'], *[x['message'] for x in quality_issues(kind, report)]]))
        for widget in (self.subjects, self.values):
            widget.setRowCount(len(self.entries))
        for i, (name, indent, bold, numeric) in enumerate(self.entries):
            label = QTableWidgetItem('  ' * indent + name.lstrip('*'))
            label.setToolTip(name)
            self.subjects.setItem(i, 0, label)
            height = 44 if len(name) > 20 else 32
            self.subjects.setRowHeight(i, height)
            self.values.setRowHeight(i, height)
            self.subjects.setWordWrap(True)
            for col, report in enumerate(self.reports):
                value = report['fields'].get(name)
                item = QTableWidgetItem(format_amount(value, divisor) if numeric else '')
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if numeric:
                    item.setToolTip(f"{report['report_date']} · {name}\n" + (
                        f"{value['value']} 元；来源分辨率 {value['resolution']} 元" if value
                        else '来源未提供；不按零处理'))
                    if value is None:
                        item.setForeground(QColor('#9b6a24'))
                self.values.setItem(i, col, item)
            for widget in (self.subjects, self.values):
                for col in range(widget.columnCount()):
                    item = widget.item(i, col)
                    font = item.font()
                    font.setBold(bold)
                    item.setFont(font)
                    if not numeric:
                        item.setBackground(QColor('#e5edf5' if indent == 0 else '#f0f4f8'))
                        item.setForeground(QColor('#233e58'))
        self.values.verticalScrollBar().setValue(scroll)
        del blocker

    def detail(self):
        i, col = self.values.currentRow(), self.values.currentColumn()
        if not 0 <= i < len(self.entries) or not 0 <= col < len(self.reports):
            return ''
        row = self.reports[col]
        item = self.values.item(i, col)
        return '\n'.join([item.toolTip(), *[x['message'] for x in quality_issues(self.kind, row)]]) if item else ''
