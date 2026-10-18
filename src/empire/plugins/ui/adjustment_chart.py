"""Price-mode and viewport controls for the adjustment page's complete OHLC result."""
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.plugins.ui.candlestick_chart import CandlestickChart
from empire.plugins.ui.common import accessible


class AdjustmentChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.stale_message = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.identity = QLabel('日 K 线 · 尚未加载')
        bar.addWidget(self.identity)
        self.mode = QComboBox()
        for name, prefix in (('原始行情', ''), ('前复权', 'forward_'), ('后复权', 'backward_')):
            self.mode.addItem(name, prefix)
        accessible(self.mode, 'K线价格口径')
        bar.addWidget(self.mode)
        self.averages = QCheckBox('MA5 / 10 / 20')
        self.averages.setChecked(True)
        bar.addWidget(self.averages)
        bar.addStretch()
        layout.addLayout(bar)
        self.problem = QLabel('红涨绿跌；所有查询交易日均参与绘图。')
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        self.detail = QLabel('移动鼠标或使用方向键查看日期和开高低收')
        self.detail.setWordWrap(True)
        accessible(self.detail, 'K线逐日价格')
        layout.addWidget(self.detail)
        self.canvas = CandlestickChart()
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        for text, action in (('放大', lambda: self.canvas.zoom(.5)), ('缩小', lambda: self.canvas.zoom(2)),
                ('向前', lambda: self.canvas.pan(-1)), ('向后', lambda: self.canvas.pan(1)),
                ('显示全部', self.canvas.full_range)):
            button = QPushButton(text)
            accessible(button, 'K线' + text)
            button.clicked.connect(action)
            controls.addWidget(button)
        self.range = QLabel('暂无 K 线')
        self.range.setWordWrap(True)
        controls.addWidget(self.range, 1)
        layout.addLayout(controls)
        self.canvas.inspected.connect(self.detail.setText)
        self.canvas.view_changed.connect(self.range.setText)
        self.mode.currentIndexChanged.connect(self.redraw)
        self.averages.toggled.connect(self.toggle_averages)

    def set_result(self, result):
        self.result = result
        self.stale_message = ''
        self.redraw()

    def redraw(self):
        if not self.result:
            return
        result, prefix = self.result, self.mode.currentData()
        self.identity.setText(f'{result["security"]} · 日 K 线 · {self.mode.currentText()}')
        problem = result.get('adjustment_problem', '')
        self.problem.setText('复权暂不可用：' + problem + '；可切换原始行情。' if problem else
            '红涨绿跌；MA5 橙 / MA10 蓝 / MA20 紫；前复权以截止日、后复权以首日为基准。')
        if prefix and problem:
            self.canvas.set_series([], message='复权暂不可用，请选择原始行情\n' + problem)
        else:
            self.canvas.set_series(result['rows'], prefix)
        if self.stale_message:
            self.mark_stale(self.stale_message)

    def toggle_averages(self, enabled):
        self.canvas.show_averages = enabled
        self.canvas.inspect(self.canvas.hover)

    def mark_stale(self, message):
        self.stale_message = message
        if self.result:
            self.problem.setText(message + f'；图表仍为 {self.result["security"]} '
                f'{self.result["base_date"]}～{self.result["anchor_date"]} 的上次结果。')
