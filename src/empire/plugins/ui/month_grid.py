"""Month display containers never infer a day's business state from its weekday."""
from calendar import Calendar
from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class MonthGrid(QWidget):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.grid = QGridLayout()
        self.buttons, self.states, self.active = [], {}, ''
        for i, label in enumerate(('一', '二', '三', '四', '五', '六', '日')):
            self.grid.addWidget(QLabel('周' + label), 0, i)
        for i in range(42):
            button = QPushButton()
            button.setMinimumHeight(55)
            button.setCheckable(True)
            button.clicked.connect(lambda _, index=i: self.choose(index))
            self.grid.addWidget(button, i//7+1, i%7)
            self.buttons.append(button)
        layout.addLayout(self.grid)
        self.note = QLabel('点击日期查看说明；未知日期不推断为休市。')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def render(self, month, states):
        year, number = map(int, month.split('-'))
        dates = list(Calendar(firstweekday=0).itermonthdates(year, number))
        self.states = states
        self.days = [d.isoformat() if d.month == number else '' for d in dates]
        for i, button in enumerate(self.buttons):
            day = self.days[i] if i < len(self.days) else ''
            button.setVisible(i < len(self.days))
            button.setEnabled(bool(day))
            label, description, style = states.get(day, ('未知', '未取得该日证明', 'unknown'))
            button.setText(f'{int(day[-2:])}\n{label}' if day else '')
            button.setAccessibleName(day + ' ' + label)
            button.setToolTip(day + '\n' + description)
            colors = {'trade': '#e9f4ef', 'closed': '#edf1f6', 'unknown': '#fff3d7',
                      'records': '#e5effc', 'outside': '#f1f1f1'}
            border = '2px solid #2860a4' if day == date.today().isoformat() else '1px solid #c1cbd7'
            button.setStyleSheet(f'QPushButton {{background:{colors.get(style, "#edf1f6")};border:{border};}}'
                                 'QPushButton:checked {border:2px solid #a1640c;}')
            button.setChecked(day == self.active)
        if self.active not in self.days:
            self.active = ''
            self.note.setText('点击日期查看说明；未知日期不推断为休市。')
        elif self.active:
            self.note.setText(self.active + ' · ' + self.states.get(
                self.active, ('未知', '未取得该日证明', 'unknown'))[1])

    def choose(self, index):
        self.active = self.days[index]
        for i, button in enumerate(self.buttons):
            button.setChecked(i < len(self.days) and self.days[i] == self.active)
        _, description, _ = self.states.get(self.active, ('未知', '未取得该日证明', 'unknown'))
        self.note.setText(self.active + ' · ' + description)
        self.selected.emit(self.active)
