"""Native bounded OHLC chart; full series, explicit zoom, drag and date inspection."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

MA_COLORS = {5: '#c88700', 10: '#356bc4', 20: '#9b51b5'}


def moving_average(values, period):
    total, result, valid = 0.0, [], 0
    for index, value in enumerate(values):
        if value is None:
            total, valid = 0.0, 0
            result.append(None)
            continue
        total += value
        valid += 1
        if valid > period:
            total -= values[index-period]
        result.append(total/period if valid >= period else None)
    return result


class CandlestickChart(QWidget):
    inspected = Signal(str)
    view_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points, self.averages = [], {}
        self.first, self.count, self.hover, self.drag_start = 0, 0, None, None
        self.show_averages = True
        self.message = '选择证券和日期后加载 K 线'
        self.setMinimumSize(320, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('股票日 K 线图')
        self.setAccessibleDescription('红涨绿跌；影线为最高最低价，实体为开收盘价。'
                                      '拖动平移，使用图表按钮缩放，方向键逐日查看。')

    def set_series(self, rows, prefix='', message=''):
        self.points = [dict(date=r['date'], events=r.get('events', []), **{k: float(r[prefix+k]) if r[prefix+k] is not None else None
                       for k in ('open', 'high', 'low', 'close')}) for r in rows]
        closes = [r['close'] for r in self.points]
        self.averages = {p: moving_average(closes, p) for p in MA_COLORS}
        self.first, self.count, self.hover = 0, len(rows), None
        self.message, self.drag_start = message, None
        self.publish_view()
        self.inspect(len(rows)-1 if rows else None)

    def plot_area(self):
        return QRectF(self.rect()).adjusted(76, 16, -20, -32)

    def publish_view(self):
        if self.points:
            self.first = max(0, min(self.first, len(self.points)-self.count))
            self.view_changed.emit(f'{self.points[self.first]["date"]} ～ '
                f'{self.points[self.first+self.count-1]["date"]} · '
                f'显示 {self.count} / {len(self.points)} 个交易日')
        else:
            self.view_changed.emit('暂无 K 线')
        self.update()

    def zoom(self, ratio):
        if not self.points:
            return
        center = self.hover if self.hover is not None else self.first+self.count//2
        minimum = min(10, len(self.points))
        self.count = max(minimum, min(len(self.points), round(self.count*ratio)))
        self.first = center-self.count//2
        self.publish_view()

    def full_range(self):
        self.first, self.count = 0, len(self.points)
        self.publish_view()

    def pan(self, direction):
        self.first += direction*max(1, self.count//2)
        self.publish_view()

    def index_at(self, x):
        area = self.plot_area()
        slot = area.width()/max(1, self.count)
        return self.first+max(0, min(self.count-1, int((x-area.left())/slot)))

    def inspect(self, index):
        self.hover = index
        if index is None:
            self.inspected.emit('移动鼠标或使用方向键查看日期和开高低收')
        else:
            row = self.points[index]
            text = f'{row["date"]}  ' + '  '.join(f'{label} {row[key]:.4f}' if row[key] is not None else f'{label} —' for label, key in
                (('开', 'open'), ('高', 'high'), ('低', 'low'), ('收', 'close')))
            if self.show_averages:
                text += '  ' + '  '.join(f'MA{p} {self.averages[p][index]:.4f}'
                    if self.averages[p][index] is not None else f'MA{p} —' for p in MA_COLORS)
            self.inspected.emit(text)
            self.setAccessibleDescription(text)
        self.update()

    def mousePressEvent(self, event):
        if self.points and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.drag_start = (event.position().x(), self.first)
            self.inspect(self.index_at(event.position().x()))

    def mouseMoveEvent(self, event):
        if not self.points:
            return
        if self.drag_start and event.buttons() & Qt.MouseButton.LeftButton:
            x, first = self.drag_start
            self.first = first-round((event.position().x()-x)*self.count/self.plot_area().width())
            self.publish_view()
        self.inspect(self.index_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        self.drag_start = None

    def keyPressEvent(self, event):
        if self.points and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if event.key() == Qt.Key.Key_Left else 1
            index = self.first if self.hover is None else self.hover+step
            index = max(0, min(len(self.points)-1, index))
            if index < self.first or index >= self.first+self.count:
                self.first = max(0, index-self.count+1) if step > 0 else index
                self.publish_view()
            self.inspect(index)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.plot_area()
        painter.fillRect(area, QColor('#fafbfd'))
        if not self.points:
            painter.setPen(QColor('#667085'))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        selected = self.points[self.first:self.first+self.count]
        prices = [r[k] for r in selected for k in ('low', 'high') if r[k] is not None]
        if self.show_averages:
            prices += [v for avg in self.averages.values()
                       for v in avg[self.first:self.first+self.count] if v is not None]
        if not prices:
            painter.setPen(QColor('#667085'))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, '当前范围原始价格无效，保留日期缺口')
            return
        low, high = min(prices), max(prices)
        margin = max((high-low)*.06, high*.005, .001)
        low, high = low-margin, high+margin
        slot = area.width()/self.count

        def position(index, value):
            return QPointF(area.left()+(index-self.first+.5)*slot,
                           area.bottom()-(value-low)/(high-low)*area.height())

        for index in range(5):
            price = high-(high-low)*index/4
            y = position(self.first, price).y()
            painter.setPen(QPen(QColor('#e2e6ed'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor('#667085'))
            painter.drawText(QRectF(0, y-9, 69, 20), Qt.AlignmentFlag.AlignRight, f'{price:.4f}')
        painter.save()
        painter.setClipRect(area)
        for offset, row in enumerate(selected):
            index = self.first+offset
            if row['close'] is None:
                painter.setPen(QPen(QColor('#a0a8b5'), 1, Qt.PenStyle.DotLine))
                x = area.left()+(offset+.5)*slot
                painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                continue
            color = QColor('#d4383a' if row['close'] >= row['open'] else '#168b64')
            painter.setPen(QPen(color, .8))
            painter.drawLine(position(index, row['high']), position(index, row['low']))
            top, bottom = position(index, max(row['open'], row['close'])), position(index, min(row['open'], row['close']))
            width = max(.7, min(16, slot*.7))
            body = QRectF(top.x()-width/2, top.y(), width, max(.8, bottom.y()-top.y()))
            painter.fillRect(body, color)
            if row['events']:
                painter.setPen(QPen(QColor('#356bc4'), 2))
                painter.drawEllipse(QPointF(top.x(), area.bottom()-6), 3, 3)
        if self.show_averages:
            for period, color in MA_COLORS.items():
                path, started = QPainterPath(), False
                for index in range(self.first, self.first+self.count):
                    value = self.averages[period][index]
                    if value is None:
                        started = False
                        continue
                    point = position(index, value)
                    if started:
                        path.lineTo(point)
                    else:
                        path.moveTo(point)
                        started = True
                painter.setPen(QPen(QColor(color), 1.2))
                painter.drawPath(path)
        if (self.hover is not None and self.first <= self.hover < self.first+self.count
                and self.points[self.hover]['close'] is not None):
            point = position(self.hover, self.points[self.hover]['close'])
            painter.setPen(QPen(QColor('#73839b'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(point.x(), area.top()), QPointF(point.x(), area.bottom()))
            painter.drawLine(QPointF(area.left(), point.y()), QPointF(area.right(), point.y()))
        painter.restore()
        painter.setPen(QColor('#667085'))
        for offset in sorted({0, self.count//2, self.count-1}):
            x = position(self.first+offset, low).x()
            x = max(area.left()+42, min(area.right()-42, x))
            painter.drawText(QRectF(x-45, area.bottom()+7, 90, 20),
                             Qt.AlignmentFlag.AlignCenter, selected[offset]['date'])
