"""Business-owned product_page; moved declarations retain existing behavior."""
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.core.redaction import redact
from empire.features.data_browser.search import CandidateSearch
from empire.features.kaipanla.contract import PRODUCTS, capability
from empire.features.kaipanla.product_chart import product_chart
from empire.features.kaipanla.product_dates import ProductDates
from empire.plugins.ui.common import accessible, rows, table
from empire.plugins.ui.preview_layout import DataNote, QueryForm
from empire.plugins.ui.queries import QueryScope

HEADERS = {
    'trend': ['分钟', '价格（元）', '均价（元）', '来源量（来源单位）', '来源标记'],
    'auction': ['来源时间', '价格（元）', '来源标记', '来源量（来源单位）'],
    'volume': ['分钟', '成交量（来源单位）', '成交额（来源单位）', '来源标记'],
    'trades': ['时间', '价格（元）', '来源标记', '来源量（来源单位）', '来源字段 4', '来源字段 5', '来源字段 6', '来源字段 7'],
    'entrust': ['分钟', '买委托量（来源单位）', '卖委托量（来源单位）', '买委托额（来源单位）', '卖委托额（来源单位）'],
    'large_order': ['分钟', '大单净额（来源单位）'],
}


class ProductPage(ProductDates, QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.future, self.applied, self.requested, self.dirty = None, None, None, False
        self.points, self.all_points, self.seqs, self.offset, self.payload = [], [], [], 0, None
        self.cursors, self.page_index, self.next_cursor, self.total = [None], 0, None, 0
        self.loaded_scope = None
        item = PRODUCTS[kind]
        layout = QVBoxLayout(self)
        title = QLabel('开盘啦' + item.title)
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = DataNote('已归档证券日数据 · 选择证券后定位最近归档日。',
            item.note + '。只读已归档数据；没有数据不能推断无成交或停牌。')
        layout.addWidget(note)
        self.market, self.code = QComboBox(), QLineEdit()
        self.market.addItems(['SZ', 'SH', 'BJ'])
        self.day = QDateEdit(QDate.currentDate())
        self.day.setDisplayFormat('yyyy-MM-dd')
        self.day.setCalendarPopup(True)
        self.day.setMinimumDate(QDate(2021, 1, 1))
        self.candidates = CandidateSearch(self, self.code, shell, 'kaipanla_' + kind, self.choose_security)
        for widget, name in ((self.market, '市场'), (self.code, '证券搜索'), (self.day, '交易日')):
            accessible(widget, item.title + name)
        find = QPushButton('查询')
        find.clicked.connect(self.find)
        self.code.returnPressed.connect(self.find)
        manage = QPushButton('采集任务')
        manage.clicked.connect(lambda: shell.navigate_management('kaipanla_' + kind))
        layout.addWidget(QueryForm([('市场', self.market), ('证券名称 / 代码', self.code),
            ('当前查询日期', self.day)], [find, manage]))
        self.status = QLabel('搜索已归档证券，选择后查看本项目最近归档日；也可输入代码和日期查询。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.install_date_navigation(layout)
        self.build_body(layout)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def build_body(self, layout):
        self.table = table(['来源序号', *HEADERS[self.kind]])
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_selected)
        self.views = QTabWidget()
        self.chart = product_chart(self.kind)
        if self.chart:
            self.views.addTab(self.chart, '当前页价格概览' if self.kind == 'trades' else '走势图')
            self.chart.inspected.connect(self.inspect_point)
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        detail_layout.addWidget(self.table, 1)
        if self.kind == 'trades':
            window = QHBoxLayout()
            self.start_time, self.end_time = QLineEdit('09:30:00'), QLineEdit('09:35:00')
            for field, name in ((self.start_time, '开始时间'), (self.end_time, '结束时间')):
                accessible(field, '分时成交明细' + name)
                field.setPlaceholderText(name + ' HH:MM:SS')
                field.returnPressed.connect(self.find)
                window.addWidget(field)
            layout.addLayout(window)
            for column in (3, 5, 6, 7, 8):
                self.table.hideColumn(column)
            more = QPushButton('显示/隐藏来源标记和未解码字段')
            more.setCheckable(True)
            more.toggled.connect(lambda enabled: [self.table.setColumnHidden(c, not enabled) for c in (3, 5, 6, 7, 8)])
            detail_layout.addWidget(more)
        self.views.addTab(details, '精确明细')
        if self.kind == 'trades':
            self.views.setCurrentWidget(details)
        paging = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        paging.addWidget(self.previous)
        paging.addWidget(self.next)
        self.position = QLabel('每页最多200条；图表读取完整有限单日序列')
        self.position.setWordWrap(True)
        paging.addWidget(self.position, 1)
        detail_layout.addLayout(paging)
        layout.addWidget(self.views, 1)

    def find(self):
        self.scope.cancel('day')
        self.future = None
        self.cursors, self.page_index, self.next_cursor = [None], 0, None
        self.applied = (self.market.currentText(), self.code.text().strip(), self.day.date().toString('yyyy-MM-dd'))
        if self.kind == 'trades':
            self.applied += (self.start_time.text().strip(), self.end_time.text().strip())
        self.dirty = True

    def copy_selected(self):
        selected = sorted({i.row() for i in self.table.selectedIndexes()})
        QApplication.clipboard().setText('\n'.join('\t'.join(self.table.item(i, j).text()
            for j in range(self.table.columnCount())) for i in selected))

    def move(self, step):
        if self.future:
            return
        if self.kind != 'trades':
            self.page_index = max(0, min(max(0, (self.total-1)//200), self.page_index+step))
            self.render()
            return
        if step < 0 and self.page_index:
            self.page_index -= 1
        elif step > 0 and self.next_cursor:
            self.page_index += 1
            self.cursors = self.cursors[:self.page_index] + [self.next_cursor]
        else:
            return
        self.dirty = True

    def inspect_point(self, index):
        if self.kind == 'trades':
            self.table.selectRow(index)
            return
        self.page_index = index//200
        self.render()
        self.table.selectRow(index % 200)

    def render(self):
        if self.kind == 'trades':
            self.chart.set_series(self.points, '当前页没有可绘制的价格；请检查时间窗', self.seqs)
        if self.kind != 'trades':
            self.offset = self.page_index*200
            self.points = self.all_points[self.offset:self.offset+200]
        seqs = self.seqs if self.kind == 'trades' else list(range(self.offset, self.offset+len(self.points)))
        rows(self.table, [[seq+1, *r] for seq, r in zip(seqs, self.points, strict=True)], keys=seqs)
        self.previous.setEnabled(self.page_index > 0)
        self.next.setEnabled(bool(self.next_cursor) if self.kind == 'trades' else self.offset+200 < self.total)
        self.position.setText(f'本页 {len(self.points)} 点 · 全日来源 {self.total} 点 · '
            + ('当前为指定时间窗，来源序号不重新编号' if self.kind == 'trades' else f'明细第{self.page_index+1}页，走势图含全部{self.total}点'))

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        self.tick_date()
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.applied:
                self.scope.discard('day', future)
            else:
                try:
                    result = self.scope.result('day', future)
                    self.points, self.all_points, self.seqs = [], [], []
                    self.payload = result.get('data') if result else None
                    self.total, self.next_cursor = 0, None
                    if result is not None:
                        if self.kind == 'trades':
                            self.points, self.seqs = result['points'], result['seqs']
                            self.offset, self.total, self.next_cursor = result['start'], result['total'], result['next_cursor']
                        elif self.kind != 'quote':
                            self.all_points = self.payload['data'][PRODUCTS[self.kind].field]
                            self.total = len(self.all_points)
                            self.page_index = min(self.page_index, max(0, (self.total-1)//200))
                    self.loaded_scope = self.requested if result else None
                    identity = f'{self.requested[1]}.{self.requested[0]} · {self.requested[2]}'
                    self.status.setText(identity + (' · 已读取归档数据，同分钟/同秒记录均保留' if result else ' · 本项目尚无已归档数据；请核对采集状态'))
                    if getattr(self, 'chart', None) and self.kind != 'trades':
                        self.chart.set_series(self.all_points, identity + ' · 未归档，不能推断无成交')
                    self.render()
                except Exception as exc:
                    message = self.scope.failure_message('day', '查询失败', redact(exc, self.shell.cfg), stale=bool(self.points or self.payload))
                    if self.loaded_scope:
                        message += f'；上次结果 {self.loaded_scope[1]}.{self.loaded_scope[0]} / {self.loaded_scope[2]}'
                    self.status.setText(message)
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.applied
            if self.kind == 'trades':
                market, code, day, start, end = self.requested
                args = (market, code, day, self.cursors[self.page_index], 200, start, end)
            else:
                args = self.requested
            self.future = self.scope.invoke('day', self.shell.runtime, capability(self.kind), 'page' if self.kind == 'trades' else 'day', *args)

    def save_ui_state(self):
        return dict(market=self.market.currentText(), code=self.code.text(), day=self.day.date().toString('yyyy-MM-dd'), applied=self.applied,
            page=self.page_index, view=self.views.currentIndex() if hasattr(self, 'views') else 0,
            cursors=list(self.cursors),
            time_window=(self.start_time.text(), self.end_time.text()) if self.kind == 'trades' else None)

    def restore_ui_state(self, state):
        self.market.setCurrentText(state['market'])
        self.code.setText(state['code'])
        self.day.setDate(QDate.fromString(state['day'], 'yyyy-MM-dd'))
        self.applied, self.dirty = state.get('applied'), bool(state.get('applied'))
        self.page_index, self.cursors = state.get('page', 0), list(state.get('cursors', [None]))
        if hasattr(self, 'views'):
            self.views.setCurrentIndex(state.get('view', 0))
        if self.kind == 'trades' and state.get('time_window'):
            self.start_time.setText(state['time_window'][0])
            self.end_time.setText(state['time_window'][1])
