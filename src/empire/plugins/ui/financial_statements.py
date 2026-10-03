"""Independent lazy financial statement pages."""
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.datasets.financial_quality import quality_issues
from empire.plugins.datasets.financial_statements import KINDS
from empire.plugins.ui.common import accessible, hint, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope
from empire.plugins.ui.statement_matrix import StatementMatrix


class StatementPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.page, self.records = shell, kind, 0, []
        self.scope, self.future, self.dirty = QueryScope(self), None, True
        self.matrix_future, self.selected, self.securities = None, None, []
        layout = QVBoxLayout(self)
        layout.addWidget(hint(KINDS[kind][0] + ' · 同花顺 · 已归档来源报告期'))
        layout.addWidget(hint('金额含来源舍入；无公告日期，不用于历史公告前选股。报表口径以来源展示为准。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), '证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('证券代码或前缀')
        self.code.setText('601139')
        self.code.returnPressed.connect(self.search)
        bar.addWidget(self.code)
        button = QPushButton('查询 / 刷新')
        button.clicked.connect(self.search)
        bar.addWidget(button)
        layout.addLayout(bar)
        self.status = hint('等待查询')
        layout.addWidget(self.status)
        self.table = table(['市场', '代码', '名称'])
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for index, width in enumerate((55, 85, 120)):
            self.table.setColumnWidth(index, width)
        self.table.itemSelectionChanged.connect(self.select_security)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        options = QHBoxLayout()
        self.period = accessible(QComboBox(), '报告期显示方式')
        self.period.addItems(['按报告期', '按年度'])
        self.unit = accessible(QComboBox(), '金额单位')
        self.unit.addItems(['万元', '元', '亿元'])
        options.addWidget(self.period)
        options.addWidget(self.unit)
        options.addStretch()
        right_layout.addLayout(options)
        self.matrix = StatementMatrix()
        right_layout.addWidget(self.matrix, 1)
        self.period.currentIndexChanged.connect(self.render_matrix)
        self.unit.currentIndexChanged.connect(self.render_matrix)
        self.matrix.values.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(right)
        splitter.setSizes([250, 900])
        layout.addWidget(splitter, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        layout.addLayout(bar)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(100)
        layout.addWidget(self.detail)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def spec(self):
        return (self.code.text().strip(), 51, self.page * 50)

    def search(self):
        self.page = 0
        self.reload()

    def move(self, step):
        self.page = max(0, self.page + step)
        self.reload()

    def reload(self):
        self.scope.cancel('statements')
        self.scope.cancel('matrix')
        self.matrix_future = None
        self.future, self.dirty = None, True
        self.tick()

    def select_security(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.securities):
            return
        stock = self.securities[index]
        key = (stock['market'], stock['code'])
        if key == self.selected:
            return
        self.selected = key
        self.scope.cancel('matrix')
        self.records = []
        self.render_matrix()
        self.matrix_future = self.scope.invoke('matrix', self.shell.runtime,
            self.kind + '.query', 'list_statements', stock['code'], 500, 0)
        self.matrix_requested = key
        self.status.setText(f"{stock['code']} {stock['name']} · 正在读取报表")

    def render_matrix(self):
        self.matrix.render(self.kind, self.records, self.period.currentIndex() == 1,
                           (10000, 1, 100000000)[self.unit.currentIndex()])
        self.show_detail()

    def show_detail(self):
        self.detail.setPlainText(self.matrix.detail())

    def save_ui_state(self):
        return {'code': self.code.text(), 'page': self.page,
                'period': self.period.currentIndex(), 'unit': self.unit.currentIndex()}

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.page, self.dirty = state['page'], True
        self.period.setCurrentIndex(state.get('period', 0))
        self.unit.setCurrentIndex(state.get('unit', 0))

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('statements', future)
            else:
                try:
                    result = self.scope.result('statements', future)
                    self.securities = result[:50]
                    preferred = self.selected
                    self.selected = None
                    rows(self.table, [[r['market'], r['code'], r['name']] for r in self.securities],
                         keys=[(r['market'], r['code']) for r in self.securities])
                    self.previous.setEnabled(self.page > 0)
                    self.next.setEnabled(len(result) > 50)
                    self.status.setText(f'第 {self.page + 1} 页 · {len(self.securities)} 只证券')
                    if self.securities:
                        index = next((i for i, r in enumerate(self.securities)
                                      if (r['market'], r['code']) == preferred), 0)
                        self.table.selectRow(index)
                        self.select_security()
                    else:
                        self.records = []
                        self.render_matrix()
                except Exception:
                    self.status.setText('查询失败，请检查数据库及查询插件状态')
        if self.matrix_future and self.matrix_future.done():
            future, self.matrix_future = self.matrix_future, None
            try:
                result = self.scope.result('matrix', future)
                if self.selected == self.matrix_requested:
                    self.records = [r for r in result if (r['market'], r['code']) == self.selected]
                    self.render_matrix()
                    issues = sum(bool(quality_issues(self.kind, r)) for r in self.records)
                    self.status.setText(f'{self.selected[1]} · {len(self.records)} 个报告期 · '
                                        f'{issues} 个报告期需核查；— 为来源未提供')
            except Exception:
                self.status.setText('报表查询失败，请检查数据库；可点击查询 / 刷新重试')
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('statements', self.shell.runtime,
                self.kind + '.query', 'list_statement_securities', *self.requested)


class FinancialUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.' + kind,))

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], partial(StatementPage, kind=self.kind),
            '数据浏览', 20 + list(KINDS).index(self.kind), '来源历史财报与金额精度',
            catalogued=True, category='基本面', source='同花顺', cache_policy='lru',
            database_tables=(KINDS[self.kind][2],),
            management=NavigationTarget('collection', NavigationContext(task_id='ths-' + self.kind))),)
