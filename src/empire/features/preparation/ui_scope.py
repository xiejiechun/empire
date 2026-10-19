"""Page-owned financial scope drafts; changing controls does not start a scan."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget

from empire.contracts.preparation_scope import FOCUSES, STUDIES, PreparationScope
from empire.plugins.ui.common import accessible, hint
from empire.plugins.ui.preview_layout import QueryForm


class PreparationScopeBar(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.purpose = accessible(QComboBox(), '范围检查用途')
        for key, label in STUDIES.items():
            self.purpose.addItem(label, key)
        self.purpose.setCurrentIndex(self.purpose.findData('value'))
        self.focus = accessible(QComboBox(), '研究方向')
        self.update_focus()
        self.purpose.currentIndexChanged.connect(self.update_focus)
        self.codes = accessible(QLineEdit(), '范围检查证券')
        self.codes.setMaxLength(700)
        self.codes.setPlaceholderText('代码逗号分隔；空=当前全股票池')
        self.start = accessible(QLineEdit(), '范围检查起始日期或报告期')
        self.end = accessible(QLineEdit(), '范围检查结束日期或报告期')
        self.start.setPlaceholderText('起始 YYYY-MM-DD；空=最早')
        self.end.setPlaceholderText('结束 YYYY-MM-DD；空=最新')
        self.index_codes = accessible(QLineEdit(), '范围检查指数')
        self.index_codes.setPlaceholderText('同花顺指数代码逗号分隔；空=目录，如1A0001')
        self.index_codes.setMaxLength(700)
        layout.addWidget(QueryForm([('研究用途', self.purpose), ('研究方向', self.focus)]))
        self.details = QWidget()
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(hint('空证券=当前全池，非历史股票池。日期对财报为报告期、对行情为交易日；草稿修改后须手动检查。'))
        detail_layout.addWidget(QueryForm([('证券代码', self.codes),
                                    ('起始日期 / 报告期', self.start), ('结束日期 / 报告期', self.end),
                                    ('同花顺指数代码', self.index_codes)]))
        layout.addWidget(self.details)
        for edit in (self.codes, self.start, self.end, self.index_codes):
            edit.textChanged.connect(self.changed)
        self.purpose.currentIndexChanged.connect(self.changed)
        self.focus.currentIndexChanged.connect(self.changed)

    def update_focus(self):
        self.focus.clear()
        for key, label in FOCUSES[self.purpose.currentData()].items():
            self.focus.addItem(label, key)

    def request(self):
        value = self.save()
        value['codes'] = [c.strip() for c in value['codes'].replace('，', ',').split(',') if c.strip()]
        value['index_codes'] = [c.strip() for c in value['index_codes'].replace('，', ',').split(',') if c.strip()]
        PreparationScope.parse(value)
        return value

    def save(self):
        return dict(study=self.purpose.currentData(), focus=self.focus.currentData(),
                    purpose='analysis' if self.purpose.currentData() == 'value' else 'historical_signal',
                    codes=self.codes.text(), scan='research',
                    start=self.start.text().strip(), end=self.end.text().strip(), index_codes=self.index_codes.text())

    def restore(self, value):
        self.purpose.setCurrentIndex(max(0, self.purpose.findData(value.get('study', 'value'))))
        self.focus.setCurrentIndex(max(0, self.focus.findData(value.get('focus', 'operating'))))
        for field in ('codes', 'start', 'end'):
            getattr(self, field).setText(value[field])
        self.index_codes.setText(value.get('index_codes', ''))
