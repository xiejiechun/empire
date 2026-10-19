"""Source-date calendar and cards, kept separate from query/page ownership."""
import calendar
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import QBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget

from empire.features.data_browser.search import CandidateSearch
from empire.plugins.ui.common import local_date
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.preview_navigation import security_context


class SuspensionPreview:
    def install_calendar_sidebar(self, layout):
        self.calendar_sidebar = QWidget()
        sidebar = QVBoxLayout(self.calendar_sidebar)
        sidebar.setContentsMargins(0, 0, 0, 0)
        self.calendar_toggle = QPushButton('展开来源日历 / 全部历史选项')
        self.calendar_toggle.setCheckable(True)
        self.calendar_toggle.toggled.connect(self.calendar_sidebar.setVisible)
        layout.addWidget(self.calendar_toggle)
        return sidebar

    def install_preview(self, results):
        self.candidates = CandidateSearch(self, self.code, self.shell, 'suspensions', self.choose_security)
        self.views = QTabWidget()
        self.cards = CardReader('停复牌来源记录卡片')
        self.cards.selected.connect(lambda i: self.table.selectRow(i))
        self.views.addTab(self.cards, '来源记录')
        self.views.addTab(self.table, '精确明细')
        results.addWidget(self.views, 1)
        self.month_future, self.month_requested, self.month_dirty = None, None, True
        self.calendar.currentPageChanged.connect(lambda *_: setattr(self, 'month_dirty', True))

    def choose_security(self, record):
        market = record['unified_code'][-2:]
        if market not in ('SH', 'SZ'):
            self.status.setText('本来源停复牌仅支持沪深A股')
            return
        self.market.setCurrentIndex(self.market.findData(market))

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        if market not in ('SH', 'SZ'):
            raise ValueError('本来源停复牌仅支持沪深A股')
        self.market.setCurrentIndex(self.market.findData(market))
        self.code.setText(code)
        if context.day:
            self.calendar.setSelectedDate(QDate.fromString(context.day, 'yyyy-MM-dd'))
            self.all_dates.setChecked(False)
        else:
            self.all_dates.setChecked(True)
        self.search()

    def render_cards(self):
        day = self.applied[2]
        self.cards.present(''.join(card(r['name'] + ' ' + r['code'] + '.' + r['market'],
            fields([('停牌时间（生效）', local_date(r['suspended_at'])),
                    ('复牌时间（生效）', local_date(r['resumed_at']) if r['resumed_at'] else '来源未提供，不代表至今停牌'),
                    ('来源说明', r['source_note']), ('原因', r['reason'])])
            + f'<p><a href="record:{i}">选择并查看完整记录</a></p>',
            '来源查询日：' + (day or '全部日期：此视图列出独立来源记录，来源出现日请按日查询'))
            for i, r in enumerate(self.records)) or '<p>暂无已归档来源记录；是否确认空日请看日历覆盖提示。</p>',
            identity=tuple(self.applied))

    def resizeEvent(self, event):
        narrow = self.width() < 820
        self.calendar_toggle.setVisible(narrow)
        self.calendar_sidebar.setVisible(not narrow or self.calendar_toggle.isChecked())
        self.body_layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        super().resizeEvent(event)

    def tick_month(self):
        spec = (f'{self.calendar.yearShown():04d}-{self.calendar.monthShown():02d}', self.applied[0], self.applied[1])
        if self.month_future and self.month_future.done():
            future, self.month_future = self.month_future, None
            try:
                result = self.query_scope.result('source-month', future)
                if spec == self.month_requested:
                    year, month = map(int, result['month'].split('-'))
                    proof = result['coverage']
                    for number in range(1, calendar.monthrange(year, month)[1]+1):
                        day = date(year, month, number).isoformat()
                        known = proof.get('from', '9999-12-31') <= day <= proof.get('through', '')
                        count = result['counts'].get(day, 0)
                        fmt = QTextCharFormat()
                        fmt.setBackground(QColor('#e5effc' if count else '#e9f4ef' if known else '#fff3d7'))
                        fmt.setToolTip(f'{day}：{count}条已归档来源记录；' + ('该日已确认' if known else '完整性未知'))
                        self.calendar.setDateTextFormat(QDate(year, month, number), fmt)
            except Exception:
                self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
                self.calendar.setToolTip('月历记录统计不可用；黄色/未标记日期完整性未知')
        if self.isVisible() and self.month_dirty and not self.month_future:
            self.month_dirty, self.month_requested = False, spec
            self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
            self.month_future = self.query_scope.invoke('source-month', self.shell.runtime,
                                                      'suspensions.query', 'source_month', *spec)
