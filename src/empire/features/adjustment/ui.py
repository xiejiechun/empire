"""Lazy read-only factor browser; independent drafts and cancellable query lifetime."""
from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
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
from empire.contracts.ui import NavigationContext, PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.features.adjustment.chart import AdjustmentChart
from empire.features.data_browser.search import CandidateSearch
from empire.plugins.ui.common import accessible, rows
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import QueryForm
from empire.plugins.ui.preview_navigation import security_context
from empire.plugins.ui.queries import QueryScope
from empire.plugins.ui.series_chart import SeriesChart


class AdjustmentPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future, self.requested, self.result, self.offset = None, None, None, 0
        self.result_spec = None
        self.restoring = None
        layout = QVBoxLayout(self)
        title = QLabel('自算复权因子与行情')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('查看原始、前复权及后复权日 K 线；复用已归档数据，缺少复权输入时仍可查看原始行情。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.market = QComboBox()
        self.market.addItem('自动识别', 'AUTO')
        for market in ('SH', 'SZ', 'BJ'):
            self.market.addItem(market, market)
        accessible(self.market, '复权证券市场')
        self.code = QLineEdit()
        self.code.setMaxLength(6)
        accessible(self.code, '复权证券代码')
        self.candidates = CandidateSearch(self, self.code, shell, 'kaipanla_quote',
            lambda r: self.market.setCurrentIndex(self.market.findData(r['unified_code'][-2:])))
        today = datetime.now(CHINA).date()
        self.start = QLineEdit((today-timedelta(days=365)).isoformat())
        self.end = QLineEdit((today-timedelta(days=1)).isoformat())
        for label, field in (('复权起始日期', self.start), ('复权截止日期', self.end)):
            field.setMaxLength(10)
            accessible(field, label)
            field.returnPressed.connect(self.find)
        self.button = QPushButton('加载K线')
        self.button.clicked.connect(self.find)
        self.code.returnPressed.connect(self.find)
        layout.addWidget(QueryForm([('市场', self.market), ('证券名称 / 代码', self.code),
            ('开始日期', self.start), ('截止日期', self.end)], [self.button]))
        self.status = QLabel('选择证券和日期后加载 K 线；日期格式 YYYY-MM-DD。图表覆盖整个查询范围。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.chart = AdjustmentChart()
        self.event_bar = QHBoxLayout()
        layout.addLayout(self.event_bar)
        self.chart.canvas.inspected.connect(self.show_event_links)
        self.tabs.addTab(self.chart, 'K线图')
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['日期', '区间累计因子', '前复权乘数', '后复权乘数', '原始收盘', '前复权收盘', '后复权收盘', '理论除权价', '事件业务键'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        accessible(self.table, '复权计算结果')
        table_layout.addWidget(self.table, 1)
        pagination = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.turn(-200))
        self.next.clicked.connect(lambda: self.turn(200))
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        pagination.addStretch()
        table_layout.addLayout(pagination)
        self.tabs.addTab(table_page, '因子与价格明细')
        self.factor_chart = SeriesChart([dict(title='区间累计复权因子 · 首日为1，仅本查询基准', fields=[(1, '累计因子')], gap=4*86400)])
        self.tabs.addTab(self.factor_chart, '因子曲线')
        layout.addWidget(self.tabs, 1)
        for field in (self.code, self.start, self.end):
            field.textChanged.connect(self.conditions_changed)
        self.market.currentIndexChanged.connect(self.conditions_changed)
        self.render()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def spec(self):
        return self.market.currentData(), self.code.text().strip(), self.start.text().strip(), self.end.text().strip()

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.code.setText(code)
        self.market.setCurrentIndex(self.market.findData(market))
        if context.start:
            self.start.setText(context.start)
        if context.end:
            self.end.setText(context.end)
        self.find()

    def conditions_changed(self):
        if self.result_spec and self.spec() != self.result_spec:
            self.chart.mark_stale('查询条件已改变，请重新加载；切换口径仍使用上次结果')

    def find(self):
        if self.future:
            return
        self.requested = self.spec()
        self.future = self.scope.invoke('adjustment', self.shell.runtime, 'adjustment.query', 'history', *self.requested)
        self.button.setEnabled(False)
        self.status.setText('正在核对已有输入并计算…')
        self.chart.mark_stale('正在加载新条件')

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if not self.future or not self.future.done():
            return
        future, self.future = self.future, None
        self.button.setEnabled(True)
        if self.requested != self.spec():
            self.scope.discard('adjustment', future)
            self.status.setText('查询条件已改变，请重新计算；表格如有内容仍是上次结果。')
            self.chart.mark_stale('查询条件已改变，请重新加载')
            return
        try:
            self.result = self.scope.result('adjustment', future)
            self.result_spec = self.requested
            self.offset = 0
            self.chart.set_result(self.result)
            self.factor_chart.set_series([[r['date'], r['factor']] for r in self.result['rows']])
            self.render()
        except Exception as exc:
            self.status.setText(self.scope.failure_message('adjustment', '无法加载', redact(exc, self.shell.cfg),
                                                         stale=bool(self.result)))
            self.chart.mark_stale('本次加载失败：' + redact(exc, self.shell.cfg))
        if self.restoring:
            state, self.restoring = self.restoring, None
            self.offset = state.get('offset', 0)
            self.set_draft(state)
            self.turn(0)

    def turn(self, amount):
        if self.result:
            self.offset = max(0, min(self.offset+amount, (len(self.result['rows'])-1)//200*200))
            self.render()

    def show_event_links(self, *_):
        while self.event_bar.count():
            self.event_bar.takeAt(0).widget().deleteLater()
        index = self.chart.canvas.hover
        if self.result and index is not None and index < len(self.result['rows']):
            row = self.result['rows'][index]
            for key in row['events']:
                kind = self.result.get('event_plans', {}).get(key)
                if kind:
                    button = QPushButton(row['date'] + ' · 查看' + ('分红送转' if kind == 'dividends' else '配股') + '方案与输入')
                    button.clicked.connect(lambda _=False, k=key, p=kind: self.shell.navigate(p,
                        NavigationContext(unified_code=self.result['security'], event_key=k)))
                    self.event_bar.addWidget(button)

    def render(self):
        self.previous.setEnabled(bool(self.result and self.offset))
        self.next.setEnabled(bool(self.result and self.offset+200 < len(self.result['rows'])))
        if not self.result:
            return
        result = self.result
        keys = ('date', 'factor', 'forward_multiplier', 'backward_multiplier', 'close', 'forward_close', 'backward_close', 'reference')
        page = result['rows'][self.offset:self.offset+200]
        rows(self.table, [[*(r[k] if k == 'date' else format(Decimal(r[k]), '.8f') if r[k] is not None else '—' for k in keys), ', '.join(r['events']) or '—'] for r in page],
             keys=[r['date'] for r in page])
        for index, row in enumerate(page):
            for column, key in enumerate(keys):
                self.table.item(index, column).setToolTip(str(row[key]) if row[key] is not None else
                    result.get('adjustment_problem') or '非除权日')
        self.status.setText(f'{result["security"]}：{result["base_date"]}～{result["anchor_date"]}，'
            f'共{len(result["rows"])}日，明细第{self.offset//200+1}页；'
            + ('仅原始行情；复权暂不可用：' + result['adjustment_problem'] if result.get('adjustment_problem') else
               '区间首日因子为1；前复权以截止日、后复权以首日为基准。'))

    def save_ui_state(self):
        return dict(market=self.market.currentIndex(), code=self.code.text(), start=self.start.text(), end=self.end.text(),
                    price_mode=self.chart.mode.currentIndex(), tab=self.tabs.currentIndex(),
                    applied=self.result_spec, offset=self.offset)

    def set_draft(self, state):
        self.market.setCurrentIndex(state['market'])
        for key in ('code', 'start', 'end'):
            getattr(self, key).setText(state[key])

    def restore_ui_state(self, state):
        self.set_draft(state)
        self.chart.mode.setCurrentIndex(state.get('price_mode', 0))
        self.tabs.setCurrentIndex(state.get('tab', 0))
        if state.get('applied'):
            market, code, start, end = state['applied']
            self.market.setCurrentIndex(self.market.findData(market))
            for key, value in (('code', code), ('start', start), ('end', end)):
                getattr(self, key).setText(value)
            self.restoring = state
            self.find()


class AdjustmentUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.adjustment', '复权计算界面', provides=('ui.pages.adjustment',),
                              description='按需计算与浏览，不启动网络任务')

    def create_pages(self):
        return (PageContribution('adjustment', '自算复权因子与行情', AdjustmentPage, '数据浏览', 30,
            '完整查询范围的日K线、均线及前后复权；缺少复权输入时提示原因', catalogued=True, category='股票行情',
            source='自算', cache_policy='lru', database_tables=('stock_daily_quote', 'dividend_plan', 'rights_issue')),)
