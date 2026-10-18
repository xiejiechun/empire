"""Index price modes preserve invalid days; auxiliary charts use the same complete range."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from empire.plugins.ui.candlestick_chart import CandlestickChart
from empire.plugins.ui.series_chart import SeriesChart


class IndexPriceChart(QWidget):
    def __init__(self):
        super().__init__()
        self.result = None
        layout = QVBoxLayout(self)
        self.identity, self.detail = QLabel('请选择指数和日期范围'), QLabel('方向键或鼠标查看逐日值')
        self.identity.setWordWrap(True)
        self.detail.setWordWrap(True)
        layout.addWidget(self.identity)
        layout.addWidget(self.detail)
        self.views = QTabWidget()
        candle_page = QWidget()
        candle_layout = QVBoxLayout(candle_page)
        self.canvas = CandlestickChart()
        self.canvas.setAccessibleName('指数日K线')
        candle_layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        for label, action in (('放大', lambda: self.canvas.zoom(.5)), ('缩小', lambda: self.canvas.zoom(2)),
                              ('向前', lambda: self.canvas.pan(-1)), ('向后', lambda: self.canvas.pan(1)),
                              ('全范围', self.canvas.full_range)):
            button = QPushButton(label)
            button.clicked.connect(action)
            controls.addWidget(button)
        candle_layout.addLayout(controls)
        self.views.addTab(candle_page, '日K线')
        self.close_chart = SeriesChart([dict(title='收盘值（点）· 其他价格异常时仍可核对有效收盘', fields=[(1, '收盘')], gap=4*86400)])
        self.views.addTab(self.close_chart, '收盘线')
        layout.addWidget(self.views, 2)
        self.amounts = SeriesChart([dict(title='成交量（来源单位）', fields=[(1, '成交量')], bars=True, zero=True, gap=None),
            dict(title='成交额（元）', fields=[(2, '成交额')], bars=True, zero=True, gap=None)])
        layout.addWidget(self.amounts, 1)
        self.canvas.inspected.connect(self.inspect)

    def inspect(self, message):
        if self.result:
            stamp = message.split('  ')[0]
            index = next((i for i, r in enumerate(self.result['rows']) if str(r['trade_date']) == stamp), None)
            if index is not None:
                self.amounts.inspect(index)
        self.detail.setText(message)

    def set_result(self, result):
        self.result = result
        raw = result['rows']
        rows = []
        for r in raw:
            valid = r['price_relation_valid'] and all(r[k] is not None for k in ('open', 'high', 'low', 'close'))
            rows.append(dict(date=str(r['trade_date']), **{k: r[k] if valid else None for k in ('open', 'high', 'low', 'close')}))
        invalid = sum(not r['price_relation_valid'] or any(r[k] is None for k in ('open', 'high', 'low', 'close')) for r in raw)
        self.identity.setText(f'{result["index_code"]} · 请求 {result["start"]}～{result["end"]} · 已读取{len(rows)}日，未按明细页截断 · '
            + (f'实际 {raw[0]["trade_date"]}～{raw[-1]["trade_date"]} · ' if raw else '')
            + f'{invalid}日四价缺失/异常保留缺口；已读行数不等于来源完整性证明。')
        self.canvas.set_series(rows, message='该范围暂无已归档日线')
        self.close_chart.set_series([[str(r['trade_date']), r['close']] for r in raw])
        self.amounts.set_series([[str(r['trade_date']),
            r['volume'] if r.get('volume_amount_valid', True) else None,
            r['amount'] if r.get('volume_amount_valid', True) else None] for r in raw])
