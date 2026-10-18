"""Native exact-point charts with shared inspection, explicit zoom and missing-time gaps."""
from datetime import date, time
from math import isfinite

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

COLORS = ('#2563a6', '#c47b11', '#168b64', '#993f95')
COLOR_NAMES = ('蓝色实线', '橙色虚线', '绿色虚线', '紫色虚线')


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def clock_value(label):
    try:
        if len(str(label)) == 10 and '-' in str(label):
            return date.fromisoformat(str(label)).toordinal() * 86400
        value = time.fromisoformat(str(label))
        return value.hour * 3600 + value.minute * 60 + value.second
    except ValueError:
        return None


class SeriesCanvas(QWidget):
    inspected = Signal(int)

    def __init__(self, title, fields, *, bars=False, zero=False, sequence=False, gap=60, positive=False):
        super().__init__()
        self.title, self.fields = title, fields
        self.bars, self.zero, self.sequence, self.gap = bars, zero, sequence, gap
        self.positive = positive
        self.points, self.hover, self.first, self.count = [], None, 0, 0
        self.sequences = None
        self.message = '选择条件后查询已归档数据'
        self.setMinimumSize(280, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)

    def set_series(self, points, message='', sequences=None):
        self.points, self.hover, self.first, self.count = points, None, 0, len(points)
        self.sequences = sequences
        self.message = message
        self.update()

    def domain(self):
        selected = self.points[self.first:self.first+self.count]
        values = [clock_value(r[0]) for r in selected]
        if self.sequence or any(v is None for v in values):
            if self.sequences is not None:
                return [s + 1 for s in self.sequences[self.first:self.first+self.count]]
            return list(range(len(selected)))
        return values

    def plotted_value(self, value):
        number = numeric(value)
        return None if self.positive and number is not None and number <= 0 else number

    def area(self):
        return self.rect().adjusted(82, 30, -24, -32)

    def inspect(self, index):
        self.hover = index
        if index is not None and 0 <= index < len(self.points):
            row = self.points[index]
            seq = self.sequences[index] + 1 if self.sequences is not None else index + 1
            self.setAccessibleDescription(f'{row[0]} · 来源序号 {seq} · ' + ' · '.join(
                f'{name} {row[field] if row[field] is not None else "—"}' for field, name in self.fields))
        self.update()

    def mouseMoveEvent(self, event):
        if not self.count:
            return
        domain, area = self.domain(), self.area()
        value = domain[0] + (event.position().x()-area.left()) / max(1, area.width()) * (domain[-1]-domain[0])
        index = min(range(len(domain)), key=lambda i: abs(domain[i]-value)) + self.first
        self.inspected.emit(index)

    def keyPressEvent(self, event):
        if self.points and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            index = (self.hover if self.hover is not None else self.first) + (-1 if event.key() == Qt.Key.Key_Left else 1)
            index = max(self.first, min(self.first+self.count-1, index))
            self.inspected.emit(index)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.area()
        painter.fillRect(area, QColor('#f8fafc'))
        painter.setPen(QColor('#536273'))
        selected = self.points[self.first:self.first+self.count]
        numbers = [self.plotted_value(r[f]) for r in selected for f, _ in self.fields]
        numbers = [v for v in numbers if v is not None]
        if not numbers:
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.message or '本范围没有可绘制的有效值；请查看明细')
            return
        lo, hi = min(numbers), max(numbers)
        if self.zero:
            lo, hi = min(0, lo), max(0, hi)
        margin = max((hi-lo)*.08, abs(hi)*.001, .001)
        lo, hi = lo-margin, hi+margin
        domain = self.domain()
        span = max(1, domain[-1]-domain[0])
        def pos(i, value):
            return QPointF(area.left() + (domain[i]-domain[0])/span*area.width(),
                           area.bottom()-(value-lo)/(hi-lo)*area.height())
        for i in range(5):
            value = hi-(hi-lo)*i/4
            y = pos(0, value).y()
            painter.setPen(QPen(QColor('#dde5ee'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor('#536273'))
            painter.drawText(QRectF(0, y-10, 77, 20), Qt.AlignmentFlag.AlignRight, f'{value:,.4g}')
        if self.zero:
            painter.setPen(QPen(QColor('#8190a4'), 1.2))
            painter.drawLine(QPointF(area.left(), pos(0, 0).y()), QPointF(area.right(), pos(0, 0).y()))
        painter.save()
        painter.setClipRect(area.adjusted(-2, -2, 2, 2))
        for line, (field, _) in enumerate(self.fields):
            path, started = QPainterPath(), False
            color = QColor(COLORS[line % len(COLORS)])
            for i, row in enumerate(selected):
                value = self.plotted_value(row[field])
                if value is None:
                    started = False
                    continue
                point = pos(i, value)
                if self.bars:
                    width = max(1, min(12, area.width()/max(1, len(selected))* .6 / len(self.fields)))
                    x = point.x() + (line-(len(self.fields)-1)/2)*width
                    base = pos(i, 0).y()
                    painter.fillRect(QRectF(x-width/2, min(base, point.y()), width,
                                           max(1, abs(base-point.y()))), color)
                else:
                    interrupted = (i > 0 and not self.sequence and self.gap is not None
                                   and domain[i]-domain[i-1] > self.gap)
                    if started and not interrupted:
                        path.lineTo(point)
                    else:
                        path.moveTo(point)
                    started = True
                    painter.setPen(QPen(color, 2))
                    painter.drawEllipse(point, 1.5, 1.5)
            if not self.bars:
                painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine if line == 0 else Qt.PenStyle.DashLine))
                painter.drawPath(path)
        if self.hover is not None and self.first <= self.hover < self.first+self.count:
            x = pos(self.hover-self.first, lo).x()
            painter.setPen(QPen(QColor('#536273'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        painter.restore()
        painter.setPen(QColor('#536273'))
        for i in sorted({0, len(selected)//2, len(selected)-1}):
            x = max(area.left()+35, min(area.right()-35, pos(i, lo).x()))
            label = str(domain[i] if self.sequences is not None else self.first+i+1) if self.sequence else str(selected[i][0])
            painter.drawText(QRectF(x-50, area.bottom()+6, 100, 22), Qt.AlignmentFlag.AlignCenter, label)


class SeriesChart(QWidget):
    inspected = Signal(int)

    def __init__(self, panels, parent=None):
        super().__init__(parent)
        self.points, self.canvases = [], []
        self.panel_labels, self.toggles = [], []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QLabel('鼠标或方向键查看精确来源值；明细可复制核对。')
        self.detail.setWordWrap(True)
        self.detail.setAccessibleName('图表所选记录')
        layout.addWidget(self.detail)
        for options in panels:
            canvas = SeriesCanvas(**options)
            canvas.inspected.connect(self.inspect)
            self.canvases.append(canvas)
            label = QLabel(canvas.title)
            label.setWordWrap(True)
            self.panel_labels.append(label)
            layout.addWidget(label)
            layout.addWidget(canvas, 1)
        controls = QHBoxLayout()
        for i, canvas in enumerate(self.canvases):
            toggle = QCheckBox(' / '.join(name for _, name in canvas.fields))
            toggle.setAccessibleName('显示或隐藏' + canvas.title)
            toggle.setToolTip(canvas.title)
            toggle.setChecked(True)
            toggle.toggled.connect(canvas.setVisible)
            toggle.toggled.connect(self.panel_labels[i].setVisible)
            self.toggles.append(toggle)
            controls.addWidget(toggle)
        layout.addLayout(controls)
        controls = QHBoxLayout()
        for name, action in (('放大', lambda: self.zoom(.5)), ('缩小', lambda: self.zoom(2)),
                             ('向前', lambda: self.pan(-1)), ('向后', lambda: self.pan(1)),
                             ('全部', self.full_range)):
            button = QPushButton(name)
            button.setAccessibleName('走势图' + name)
            button.clicked.connect(action)
            controls.addWidget(button)
        layout.addLayout(controls)

    def set_series(self, points, message='', sequences=None):
        if sequences is not None and len(sequences) != len(points):
            raise ValueError('图表点与来源序号数量不一致')
        self.points = points
        self.sequences = sequences
        for canvas in self.canvases:
            canvas.set_series(points, message, sequences)
        labels = [f'{title}（{COLOR_NAMES[i % len(COLORS)] if not canvas.bars else "柱形"}）' for canvas in self.canvases
                  for i, (_, title) in enumerate(canvas.fields)]
        stamps = f' · {points[0][0]}～{points[-1][0]}' if points else ''
        self.detail.setText(' · '.join(labels) + (f' · {len(points)}个来源点，未抽样' + stamps if points else ''))

    def inspect(self, index):
        for canvas in self.canvases:
            canvas.inspect(index)
        if 0 <= index < len(self.points):
            row = self.points[index]
            seq = self.sequences[index] + 1 if self.sequences is not None else index + 1
            self.detail.setText(f'{row[0]} · 来源序号 {seq} · ' + ' · '.join(
                f'{name}: {row[field] if row[field] is not None else "—"}'
                for canvas in self.canvases for field, name in canvas.fields))
            self.inspected.emit(index)

    def zoom(self, factor):
        for canvas in self.canvases:
            canvas.count = max(1, min(len(self.points), round(canvas.count*factor))) if self.points else 0
            canvas.first = min(canvas.first, max(0, len(self.points)-canvas.count))
            canvas.update()

    def pan(self, direction):
        for canvas in self.canvases:
            canvas.first = max(0, min(len(self.points)-canvas.count,
                                     canvas.first+direction*max(1, canvas.count//3)))
            canvas.update()

    def full_range(self):
        for canvas in self.canvases:
            canvas.first, canvas.count = 0, len(self.points)
            canvas.update()
