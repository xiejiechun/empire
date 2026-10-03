"""Lazy security/day browser for source trend points and lossless auction points."""
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import accessible, restore_table_identity, rows, table_identity_state
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class IntradayPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future, self.applied, self.requested, self.dirty = None, None, None, False
        layout = QVBoxLayout(self)
        title = QLabel('开盘啦历史分时及竞价')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('当前上市股票的历史数据；竞价按来源序号保留同分钟多点。'
                      '只有分钟标签，来源量及标记原样展示，不是逐笔成交或分钟 OHLC。')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.market = QComboBox()
        self.market.addItems(['SZ', 'SH', 'BJ'])
        self.code = QLineEdit('000001')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('六位证券代码')
        self.day = QDateEdit(QDate.currentDate().addDays(-1))
        self.day.setDisplayFormat('yyyy-MM-dd')
        self.day.setMinimumDate(QDate(2021, 1, 1))
        self.day.setCalendarPopup(True)
        for widget, name in ((self.market, '分时市场'), (self.code, '分时证券代码'), (self.day, '分时交易日期')):
            accessible(widget, name)
            bar.addWidget(widget)
        find = QPushButton('查询')
        find.clicked.connect(self.find)
        self.code.returnPressed.connect(self.find)
        bar.addWidget(find)
        manage = QPushButton('前往采集任务')
        manage.clicked.connect(lambda: shell.navigate_management('intraday'))
        bar.addWidget(manage)
        bar.addStretch()
        layout.addLayout(bar)
        self.status = QLabel('选择证券与交易日期，读取 MySQL 已归档数据。未归档或未上市的日期不能推断为零成交。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        tabs = QTabWidget()
        self.trend = QTableWidget(0, 6)
        self.auction = QTableWidget(0, 5)
        for table, headers, label in (
            (self.trend, ['序号', '分钟', '价格', '均价', '来源量', '来源标记'], '普通分时'),
            (self.auction, ['来源序号', '分钟', '价格', '来源标记', '来源量'], '开盘竞价')):
            table.setHorizontalHeaderLabels(headers)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.horizontalHeader().setStretchLastSection(True)
            accessible(table, label + '已归档点位')
            tabs.addTab(table, label)
        layout.addWidget(tabs, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def find(self):
        self.applied = (self.market.currentText(), self.code.text().strip(), self.day.date().toString('yyyy-MM-dd'))
        self.dirty = True

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.applied:
                self.scope.discard('day', future)
            else:
                try:
                    result = self.scope.result('day', future)
                    if result is None:
                        rows(self.trend, [])
                        rows(self.auction, [])
                        self.status.setText('这个证券日没有已归档分时；可能尚未采集、未上市、休市或停牌，请核对采集状态。')
                    else:
                        data = result['data']
                        rows(self.trend, [[i, *point] for i, point in enumerate(data['trend'], 1)],
                             keys=[(data['trade_date'], i) for i in range(len(data['trend']))])
                        rows(self.auction, [[i, *point] for i, point in enumerate(data['auction'], 1)],
                             keys=[(data['trade_date'], i) for i in range(len(data['auction']))])
                        self.status.setText(f"{data['market']}:{data['code']} / {data['trade_date']}；"
                            f"普通分时 {len(data['trend'])} 点，开盘竞价 {len(data['auction'])} 点；昨收 {data['preclose_px']}。"
                            '收盘竞价时段包含在普通分时末段；量单位及标记尚未作成交语义转换。'
                            + ('历史来源代码 ' + '、'.join(sorted(data['aliases'])) + ' 已核实对应当前证券。'
                               if data['aliases'] else ''))
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('day', '分时查询失败', redact(exc, self.shell.cfg),
                        stale=self.trend.rowCount() > 0))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.applied
            self.future = self.scope.invoke('day', self.shell.runtime, 'intraday.query', 'day', *self.requested)

    def save_ui_state(self):
        return dict(market=self.market.currentText(), code=self.code.text(), day=self.day.date().toString('yyyy-MM-dd'),
                    applied=self.applied, trend=table_identity_state(self.trend), auction=table_identity_state(self.auction))

    def restore_ui_state(self, state):
        self.market.setCurrentText(state['market'])
        self.code.setText(state['code'])
        self.day.setDate(QDate.fromString(state['day'], 'yyyy-MM-dd'))
        self.applied, self.dirty = state.get('applied'), bool(state.get('applied'))
        restore_table_identity(self.trend, state.get('trend', {}))
        restore_table_identity(self.auction, state.get('auction', {}))


class IntradayUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.intraday', '开盘啦分时界面', provides=('ui.pages.intraday',),
                              description='按需查询已归档证券日和原顺序竞价点')

    def create_pages(self):
        return (PageContribution('intraday', '开盘啦分时及竞价', IntradayPage, '数据浏览', 11,
            '2021 年起当前上市证券分时与开盘竞价；来源分钟标签，竞价点不按分钟合并',
            database_tables=('stock_intraday',), catalogued=True, category='高频行情', source='开盘啦',
            cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='kaipanla-intraday'))),)
