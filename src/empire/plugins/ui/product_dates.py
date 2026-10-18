"""Bounded navigation to archived project-specific days, preserving editable drafts."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from empire.core.redaction import redact
from empire.plugins.collectors.kaipanla_kinds import capability
from empire.plugins.ui.preview_navigation import security_context


class ProductDates:
    def install_date_navigation(self, layout):
        self.date_future, self.date_requested = None, None
        bar = QHBoxLayout()
        for label, direction in (('上一归档日', -1), ('最近归档日', 0), ('下一归档日', 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda _, step=direction: self.navigate_day(step))
            bar.addWidget(button)
        layout.addLayout(bar)

    def choose_security(self, record):
        self.market.setCurrentText(record['unified_code'][-2:])
        self.navigate_day(0)

    def navigate_day(self, direction):
        self.date_requested = (self.market.currentText(), self.code.text().strip(),
                               self.day.date().toString('yyyy-MM-dd'), direction)
        self.date_future = self.scope.invoke('date', self.shell.runtime, capability(self.kind),
                                            'archived_date', *self.date_requested)
        self.status.setText('正在查找该证券本项目的已归档日期；不会启动采集。')

    def tick_date(self):
        if not self.date_future or not self.date_future.done():
            return
        future, self.date_future = self.date_future, None
        requested = self.date_requested
        if requested[:3] != (self.market.currentText(), self.code.text().strip(), self.day.date().toString('yyyy-MM-dd')):
            self.scope.discard('date', future)
            return
        try:
            day = self.scope.result('date', future)
            if day:
                self.day.setDate(QDate.fromString(day, 'yyyy-MM-dd'))
                self.find()
            else:
                self.status.setText('该方向没有已归档日期；当前结果和日期保留。')
        except Exception as exc:
            self.status.setText('归档日期查询失败：' + redact(exc, self.shell.cfg))

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.code.setText(code)
        self.market.setCurrentText(market)
        if context.day:
            self.day.setDate(QDate.fromString(context.day, 'yyyy-MM-dd'))
            self.find()
        else:
            self.navigate_day(0)
