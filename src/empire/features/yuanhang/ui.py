"""Lazy native-history browser with explicit applied filters and cancellable reads."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.yuanhang.contract import TABLE_COLUMNS
from empire.plugins.ui.common import accessible, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import DataNote, QueryForm
from empire.plugins.ui.queries import QueryScope

MODES = (
    ('日线（不复权）', 'prices', (), ('trade_date', 'open', 'high', 'low', 'close', 'volume_shares', 'amount_yuan', 'quality_flags'),
     ('日期', '开盘/元', '最高/元', '最低/元', '收盘/元', '成交量/股', '成交额/元', '来源量价质量')),
    ('分红送转配股', 'actions', (), ('ex_date', 'bonus_ratio', 'transfer_ratio', 'rights_ratio', 'rights_price', 'cash_per_share'),
     ('除权日', '送股或缩股/原股', '转增/原股', '配股/原股', '配股价/元', '现金/原股')),
    *((label, 'capital_points', (kind,), ('effective_date', 'shares'), ('生效日', '股数'))
      for label, kind in (('总股本', 'total'), ('普通流通股', 'circulating'), ('自由流通股', 'free_float'))),
)


class YuanhangPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future, self.after, self.next_after = None, None, None
        self.applied, self.requested, self.history = None, None, []
        self.dirty = False
        layout = QVBoxLayout(self)
        title = QLabel('远航版历史日线、权息与股本')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(DataNote('选择证券和数据类型，查询已归档历史。',
            '日线为不复权原值，成交量为股；源量额缺值显示“未知”，OHLC异常阻止该范围复权。权息日期为生效日，不代表当时已公告；'
            '送缩股负值表示缩股，同日多事件分别保留、复权需核实。股本按各口径变动日保存，未知流通股不填0或沿用旧值。初始化进度请查看采集任务。'))
        self.code = accessible(QLineEdit('000001.SZ'), '远航版统一证券代码')
        self.mode = accessible(QComboBox(), '远航版历史数据类型')
        self.mode.addItems([m[0] for m in MODES])
        self.start = accessible(QLineEdit('1900-01-01'), '远航版历史开始日期')
        self.end = accessible(QLineEdit('2100-12-31'), '远航版历史结束日期')
        for w in (self.start, self.end):
            w.setMaxLength(10)
        self.code.setMaxLength(9)
        self.code.returnPressed.connect(self.find)
        button = QPushButton('查询')
        button.clicked.connect(self.find)
        layout.addWidget(QueryForm([('证券代码，如000001.SZ', self.code), ('数据类型', self.mode),
                                   ('起始日期', self.start), ('截止日期', self.end)], [button]))
        self.status = QLabel('点击查询读取已归档历史；每页200条。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = table(MODES[0][4])
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.back_button, self.next_button = QPushButton('上一页'), QPushButton('下一页')
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.forward)
        for b in (self.back_button, self.next_button):
            b.setEnabled(False)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def find(self):
        self.applied = (self.code.text().strip(), self.mode.currentIndex(), self.start.text().strip(), self.end.text().strip())
        self.after, self.history, self.dirty = None, [], True

    def forward(self):
        if self.next_after:
            self.history.append(self.after)
            self.after, self.dirty = self.next_after, True

    def back(self):
        if self.history:
            self.after, self.dirty = self.history.pop(), True

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != (self.applied, self.after):
                self.scope.discard('history', future)
            else:
                try:
                    result = self.scope.result('history', future)
                    mode = MODES[self.applied[1]]
                    self.table.setColumnCount(len(mode[4]))
                    self.table.setHorizontalHeaderLabels(mode[4])
                    rows(self.table, [[('OHLC异常' if r.get(k) else '正常') if k == 'quality_flags'
                                      else str(r[k]) if r[k] is not None else '未知' for k in mode[3]]
                                     for r in result['rows']], keys=[str(r[mode[3][0]]) for r in result['rows']])
                    self.next_after = result['next']
                    coverage = result.get('coverage', {})
                    suffix = (f"\n增量覆盖截至 {coverage.get('through') or '未确认'} · 完整历史最后核验 "
                              f"{coverage.get('full_checked') or '未确认'}") if coverage else ''
                    self.status.setText(f'{self.applied[0]} · {mode[0]} · 本页{len(result["rows"])}条' + suffix)
                    self.back_button.setEnabled(bool(self.history))
                    self.next_button.setEnabled(bool(self.next_after))
                except Exception as exc:
                    self.status.setText(redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty = False
            self.requested = (self.applied, self.after)
            code, index, start, end = self.applied
            mode = MODES[index]
            self.future = self.scope.invoke('history', self.shell.runtime, 'yuanhang.history.query',
                mode[1], code, *mode[2], start, end, self.after, 200)

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
        if context.start:
            self.start.setText(context.start)
        if context.end:
            self.end.setText(context.end)
        if context.event_key:
            self.mode.setCurrentIndex(1)
        self.find()


class YuanhangUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang', '远航历史行情页面',
        provides=('ui.pages.yuanhang',), description='按需创建日线、权息与三种股本浏览页面')

    def create_pages(self):
        return (PageContribution('yuanhang', '远航历史行情', YuanhangPage, '数据浏览', 60,
            '不复权日线、分红送转配股及历史股本', catalogued=True, category='行情数据',
            source='同花顺远航版', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS),
            management=NavigationTarget('collection', NavigationContext(task_id='ths-yuanhang-prices'))),)
