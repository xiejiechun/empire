"""Source-period summaries and optional charts; never derive standalone quarters."""
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from empire.plugins.datasets.financial_statements import REQUIRED
from empire.plugins.ui.series_chart import SeriesChart
from empire.plugins.ui.statement_matrix import format_amount


class StatementPreview(QWidget):
    def __init__(self, kind):
        super().__init__()
        self.kind, self.reports, self.divisor = kind, [], 10000
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('摘要报告期'))
        self.period = QComboBox()
        self.period.setAccessibleName('财报摘要报告期')
        self.period.currentIndexChanged.connect(self.summary)
        controls.addWidget(self.period)
        layout.addLayout(controls)
        self.label = QLabel('选择证券查看来源科目；— 为来源未提供。')
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)
        keys = REQUIRED[kind][:3]
        self.keys = keys
        self.chart = SeriesChart([dict(title='来源报告期金额（亿元）· ' + ('时点口径' if kind == 'balance' else '累计口径，不是单季度'),
            fields=[(i+1, k.lstrip('*')) for i, k in enumerate(keys)], zero=kind != 'income', gap=None)])

    def set_reports(self, reports, divisor):
        preferred = getattr(self, 'restored_period', self.period.currentData())
        if hasattr(self, 'restored_period'):
            del self.restored_period
        self.reports, self.divisor = sorted(reports, key=lambda r: r['report_date'], reverse=True), divisor
        self.period.blockSignals(True)
        self.period.clear()
        for r in self.reports:
            self.period.addItem(r['report_date'], r['report_date'])
        self.period.setCurrentIndex(max(0, self.period.findData(preferred)))
        self.period.blockSignals(False)
        points = [[r['report_date'], *[Decimal(r['fields'][key]['value']) / Decimal(100000000)
            if r['fields'].get(key) else None for key in self.keys]] for r in reversed(self.reports)]
        self.chart.set_series(points)
        self.summary()

    def summary(self):
        r = next((r for r in self.reports if r['report_date'] == self.period.currentData()), None)
        if not r:
            self.label.setText('没有可用来源报告期；— 不按零处理。')
            return
        unit = {1: '元', 10000: '万元', 100000000: '亿元'}[self.divisor]
        self.label.setText(r['report_date'] + ' · ' + ' · '.join(k.lstrip('*') + ' ' + format_amount(r['fields'].get(k), self.divisor)
            + unit for k in self.keys) + ('；资产、负债及权益按来源值分别列示，不补齐结构差额。' if self.kind == 'balance' else
            '；来源累计金额，不推导单季度、同比或历史公布时点。'))
