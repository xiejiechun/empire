"""Page-owned financial scope drafts; changing controls does not start a scan."""
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.ui.common import accessible


class PreparationScopeBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.purpose = accessible(QComboBox(), '范围检查用途')
        self.purpose.addItem('数据分析 / 财务估值', 'analysis')
        self.purpose.addItem('历史选股回测', 'historical_signal')
        self.codes = accessible(QLineEdit('601139'), '范围检查证券')
        self.codes.setPlaceholderText('代码逗号分隔；空=当前全股票池')
        self.start = accessible(QLineEdit(), '范围检查起始日期或报告期')
        self.end = accessible(QLineEdit(), '范围检查结束日期或报告期')
        self.start.setPlaceholderText('起始 YYYY-MM-DD；空=最早')
        self.end.setPlaceholderText('结束 YYYY-MM-DD；空=最新')
        for widget in (self.purpose, self.codes, self.start, self.end):
            layout.addWidget(widget)

    def request(self):
        value = self.save()
        value['codes'] = [c.strip() for c in value['codes'].replace('，', ',').split(',') if c.strip()]
        PreparationScope.parse(value)
        return value

    def save(self):
        return dict(purpose=self.purpose.currentData(), codes=self.codes.text(),
                    start=self.start.text().strip(), end=self.end.text().strip())

    def restore(self, value):
        self.purpose.setCurrentIndex(max(0, self.purpose.findData(value['purpose'])))
        for field in ('codes', 'start', 'end'):
            getattr(self, field).setText(value[field])
