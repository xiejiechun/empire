"""Archived minute prices only; no playback or collection side effects."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from empire.plugins.ui.kaipanla_quote_format import GREEN, RED, display


class QuoteChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points, self.reference, self.message, self.hover = [], 0, '尚未查询分时走势', None
        self.setMinimumSize(320, 260)
        self.setMouseTracking(True)
        self.setAccessibleName('已归档分时价格及均价走势')
        self.setAccessibleDescription('黑线价格，橙线均价；鼠标移动查看分钟价格。')

    def set_series(self, points, reference, message=''):
        self.points, self.reference, self.message, self.hover = points, reference or 0, message, None
        self.update()

    def mouseMoveEvent(self, event):
        if self.points:
            self.hover = max(0, min(len(self.points) - 1,
                round((event.position().x() - 55) / max(1, self.width() - 75) * (len(self.points) - 1))))
            row = self.points[self.hover]
            QToolTip.showText(event.globalPosition().toPoint(),
                f'{row[0]}  价格 {display(row[1], "price")}  均价 {display(row[2], "price")}', self)
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(55, 24, -20, -34)
        painter.fillRect(area, QColor('#fafbfd'))
        if not self.points:
            painter.setPen(QColor('#667085'))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        prices = [r[i] for r in self.points for i in (1, 2) if r[i] > 0]
        if not prices:
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, '该日分时没有有效价格')
            return
        center = self.reference if self.reference > 0 else (min(prices) + max(prices)) / 2
        spread = max(max(abs(p - center) for p in prices), center * .005, .01)
        low, high = center - spread, center + spread
        def position(index, price):
            return QPointF(area.left() + index / max(1, len(self.points) - 1) * area.width(),
                area.bottom() - (price - low) / (high - low) * area.height())
        for index in range(5):
            price = high - (high - low) * index / 4
            y = position(0, price).y()
            painter.setPen(QPen(QColor('#e2e6ed'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor(RED if price > center else GREEN if price < center else '#667085'))
            painter.drawText(0, int(y) - 8, 50, 20, Qt.AlignmentFlag.AlignRight, f'{price:.2f}')
        for field, color in ((1, '#30343b'), (2, '#dca12b')):
            path, started = QPainterPath(), False
            for index, row in enumerate(self.points):
                if row[field] <= 0:
                    started = False
                    continue
                point = position(index, row[field])
                if started:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    started = True
            painter.setPen(QPen(QColor(color), 1.5))
            painter.drawPath(path)
        painter.setPen(QColor('#667085'))
        painter.drawText(area.left(), 0, area.width(), 20, Qt.AlignmentFlag.AlignLeft, '价格  ━    均价  ━')
        for fraction, clock in ((0, '09:30'), (.5, '11:30 / 13:00'), (1, '15:00')):
            x = area.left() + fraction * area.width()
            painter.drawText(int(x) - 50, area.bottom() + 9, 100, 20, Qt.AlignmentFlag.AlignCenter, clock)
        if self.hover is not None:
            x = position(self.hover, center).x()
            painter.setPen(QPen(QColor('#8190a4'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
