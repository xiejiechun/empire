"""Quote summary and ordered book, arranged like the source stock screen."""
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from empire.features.kaipanla.quote_chart import QuoteChart
from empire.features.kaipanla.quote_format import (
    FIELDS,
    GREEN,
    NEUTRAL,
    RED,
    display,
    number,
    price_color,
)
from empire.plugins.ui.common import accessible, rows, table
from empire.plugins.ui.preview_layout import compact_columns


class QuoteView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data, self.reference = {}, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.identity = QLabel('选择证券及交易日')
        self.identity.setObjectName('sectionTitle')
        self.identity.setWordWrap(True)
        layout.addWidget(self.identity)
        top = QFrame()
        top.setObjectName('card')
        header = QHBoxLayout(top)
        price_box = QVBoxLayout()
        self.price, self.change = QLabel('—'), QLabel('—')
        self.price.setAccessibleName('历史盘口最新价')
        self.change.setAccessibleName('历史盘口涨跌额与涨跌幅')
        price_box.addWidget(self.price)
        price_box.addWidget(self.change)
        header.addLayout(price_box, 1)
        self.metrics = {}
        summary = QGridLayout()
        for index, (field, title, style) in enumerate(FIELDS[:6]):
            value = QLabel('—')
            accessible(value, '历史盘口' + title)
            summary.addWidget(QLabel(title), index // 3, index % 3 * 2)
            summary.addWidget(value, index // 3, index % 3 * 2 + 1)
            self.metrics[field] = (value, style)
        header.addLayout(summary, 4)
        layout.addWidget(top)
        middle = self.middle = QSplitter(Qt.Orientation.Horizontal)
        self.chart = QuoteChart()
        middle.addWidget(self.chart)
        book_area = QWidget()
        book_area.setMinimumWidth(280)
        book_layout = QVBoxLayout(book_area)
        book_layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('历史盘口'))
        self.depth = accessible(QComboBox(), '历史盘口档位显示')
        self.depth.addItems(['五档', '十档'])
        self.depth.currentIndexChanged.connect(self.render_book)
        controls.addWidget(self.depth)
        book_layout.addLayout(controls)
        self.sell_total, self.buy_total = QLabel('总卖 —'), QLabel('总买 —')
        book_layout.addWidget(self.sell_total)
        self.book = table(['档位', '价格', '数量（来源单位）'])
        compact_columns(self.book, (60, 80, 140), 2)
        self.book.setAccessibleName('历史盘口买卖档位')
        self.book.setMinimumHeight(410)
        book_layout.addWidget(self.book)
        book_layout.addWidget(self.buy_total)
        middle.addWidget(book_area)
        middle.setSizes([600, 320])
        layout.addWidget(middle)
        self.chart_note = QLabel('蓝实线价格，橙虚线均价；走势来自本证券本日独立分时归档。')
        self.chart_note.setWordWrap(True)
        self.chart_note.setObjectName('muted')
        layout.addWidget(self.chart_note)
        layout.addWidget(QLabel('估值、股本及其他日统计（来源口径）'))
        details = QGridLayout()
        for index, (field, title, style) in enumerate(FIELDS[6:]):
            value = QLabel('—')
            accessible(value, '历史盘口' + title)
            details.addWidget(QLabel(title), index // 3, index % 3 * 2)
            details.addWidget(value, index // 3, index % 3 * 2 + 1)
            self.metrics[field] = (value, style)
        layout.addLayout(details)
        note = QLabel('静态证券日快照；没有全天盘口回放。万／亿仅缩写来源数值，成交量及委托数量保留来源单位。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        layout.addWidget(note)
        self.more = QPushButton('更多来源字段')
        self.more.setCheckable(True)
        layout.addWidget(self.more)
        self.extra = table(['来源字段', '值'])
        self.extra.setAccessibleName('历史盘口附加来源字段')
        self.extra.setVisible(False)
        self.more.toggled.connect(self.extra.setVisible)
        layout.addWidget(self.extra)

    def resizeEvent(self, event):
        self.middle.setOrientation(Qt.Orientation.Vertical if self.width() < 800 else Qt.Orientation.Horizontal)
        super().resizeEvent(event)

    def set_quote(self, record, identity):
        self.data = record['data'] if record else {}
        self.reference = self.data.get('preclose_px')
        if identity:
            market, code, day = identity
            name = self.data.get('name', '')
            self.identity.setText(f'{name}  {code}.{market}  ·  {day} 历史快照')
        else:
            self.identity.setText('选择证券及交易日')
        real = self.data.get('real', {})
        color = price_color(real.get('last_px'), self.reference)
        self.price.setText(display(real.get('last_px'), 'price'))
        self.price.setStyleSheet(f'font-size: 30pt; font-weight: 600; color: {color};')
        delta, rate = real.get('px_change'), real.get('px_change_rate')
        self.change.setText(('+' if number(delta) and delta > 0 else '') + display(delta) + '  '
            + ('+' if number(rate) and rate > 0 else '') + display(rate, 'percent'))
        self.change.setStyleSheet(f'font-size: 13pt; color: {color};')
        for field, (label, style) in self.metrics.items():
            label.setText(display(real.get(field), style))
            color = price_color(real.get(field), self.reference) if style == 'price' else NEUTRAL
            label.setStyleSheet(f'font-weight: 600; color: {color};')
            label.setToolTip(f'来源字段 {field}；原值 {real.get(field, "缺失")}')
        self.render_book()
        known_real = {field for field, _, _ in FIELDS} | {'last_px', 'px_change', 'px_change_rate'}
        extra = [[f'real.{key}', str(value)] for key, value in real.items() if key not in known_real]
        book = self.data.get('weituo', {})
        extra += [[f'weituo.{key}', str(value)] for key, value in book.items()
                  if key not in {side + str(i) for side in ('s', 'b') for i in range(1, 11)} | {'totalb', 'totals'}]
        extra += [[key, json.dumps(value, ensure_ascii=False)] for key, value in self.data.items()
                  if key not in {'real', 'weituo', 'name'}]
        rows(self.extra, extra)
        self.chart.set_series([], self.reference, '正在读取已归档分时走势' if record else '本证券日本项没有已归档数据')

    def render_book(self):
        book = self.data.get('weituo', {})
        depth = 5 if self.depth.currentIndex() == 0 else 10
        values = []
        for side, levels in (('s', range(depth, 0, -1)), ('b', range(1, depth + 1))):
            for level in levels:
                price, quantity = book.get(side + str(level), [None, None])
                values.append([('卖' if side == 's' else '买') + str(level),
                    display(price, 'price'), display(quantity) if number(price) and price > 0 else '—'])
        rows(self.book, values)
        for index in range(len(values)):
            for column in range(3):
                self.book.item(index, column).setBackground(QBrush())
            self.book.item(index, 1).setForeground(QColor(price_color(
                book.get(('s' + str(depth - index)) if index < depth else ('b' + str(index - depth + 1)), [None])[0],
                self.reference)))
            self.book.item(index, 2).setForeground(QColor('#4187c8'))
            if index == depth:
                for column in range(3):
                    self.book.item(index, column).setBackground(QColor('#fff3f3'))
            for column in range(3):
                self.book.item(index, column).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.sell_total.setText('总卖 ' + display(book.get('totals')))
        self.sell_total.setStyleSheet(f'color: {GREEN};')
        self.buy_total.setText('总买 ' + display(book.get('totalb')))
        self.buy_total.setStyleSheet(f'color: {RED};')
