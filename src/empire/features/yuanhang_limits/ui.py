"""Lazy browsing page with explicit filter application and scoped read ownership."""
from datetime import datetime

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
from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import POOLS, TABLE_COLUMNS, TIME_FIELDS, project
from empire.plugins.ui.common import accessible, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import DataNote, QueryForm
from empire.plugins.ui.queries import QueryScope

FIELDS = ('trade_date', 'pool_type', 'unified_code', 'name', 'latest', 'change_rate', 'turnover_rate',
          'turnover', 'currency_value', 'sum_market_value', 'order_amount', 'order_volume', 'high_days',
          'first_limit_up_time', 'last_limit_up_time', 'open_num', 'reason_type', 'limit_up_type',
          'first_limit_down_time', 'last_limit_down_time', 'limit_down_type', 'limit_up_suc_rate',
          'rise_rate', 'market_type', 'is_new', 'is_again_limit', 'change_tag', 'top_concept')
LABELS = ('日期', '池', '证券', '名称', '价格/元', '涨跌幅/%', '换手率/%', '成交额/元', '流通市值/元',
          '总市值/元', '封单额/元', '来源封单量', 'N天M板', '首次涨停', '最后涨停', '开板次数', '原因摘要',
          '涨停类型', '首次跌停', '最后跌停', '跌停类型', '成功率/比例', '来源涨速', '市场类别',
          '新股标记', '回封标记', '来源状态', '关联概念')


def display_value(key, value):
    if value is None:
        return '未知'
    if key in TIME_FIELDS and isinstance(value, datetime) and value.replace(tzinfo=CHINA).timestamp() == 0:
        return '未知（来源0）'
    return str(value)


class LimitsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future = self.applied = self.requested = None
        self.after, self.next_after, self.history, self.dirty = None, None, [], False
        layout = QVBoxLayout(self)
        title = QLabel('远航版涨跌停分析')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(DataNote('查询日终五池、证券原因，或查看Redis盘中变化与回放。',
            '日终结果存MySQL，盘中变化只存Redis，最长72小时且受容量限制；HS/GEM2STAR口径；不同池的空值独立保留。原因无可靠公布时间，不能当作盘中已知信号。'
            '来源报告空池与未采集分开显示；空池不证明更早历史不存在。'))
        self.mode = accessible(QComboBox(), '涨停分析查询方式')
        self.mode.addItems(['日期池（日终）', '证券历史（日终）', '证券日原因', '盘中最新/回放（Redis）', '盘中变化时刻（Redis）'])
        self.pool = accessible(QComboBox(), '涨停分析池')
        self.pool.addItems(list(POOLS.values()))
        self.code = accessible(QLineEdit('000001.SZ'), '涨停分析证券代码')
        self.start = accessible(QLineEdit(datetime.now(CHINA).date().isoformat()), '涨停分析日期或开始日期')
        self.end = accessible(QLineEdit(datetime.now(CHINA).date().isoformat()), '涨停分析结束日期')
        self.replay = accessible(QLineEdit(), '盘中回放北京时间')
        self.replay.setPlaceholderText('HH:MM:SS，留空查最新')
        self.replay.setMaxLength(15)
        self.code.setMaxLength(9)
        self.start.setMaxLength(10)
        self.end.setMaxLength(10)
        button = QPushButton('查询')
        button.clicked.connect(self.apply_filters)
        layout.addWidget(QueryForm([('查询方式', self.mode), ('日期池类型', self.pool), ('证券代码', self.code),
                                   ('日期/开始日期', self.start), ('历史结束日期', self.end),
                                   ('盘中回放时刻', self.replay)], [button]))
        self.status = QLabel('点击查询读取已归档数据；日期池及历史每页200条。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = table(LABELS)
        self.result_rows = []
        self.table.cellDoubleClicked.connect(self.replay_row)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.previous, self.following = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(self.back)
        self.following.clicked.connect(self.forward)
        for button in (self.previous, self.following):
            button.setEnabled(False)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def apply_filters(self):
        self.applied = (self.mode.currentIndex(), list(POOLS)[self.pool.currentIndex()], self.code.text().strip(),
                        self.start.text().strip(), self.end.text().strip(), self.replay.text().strip())
        self.after, self.history, self.dirty = None, [], True

    def forward(self):
        if self.next_after is not None:
            self.history.append(self.after)
            self.after, self.dirty = self.next_after, True

    def back(self):
        if self.history:
            self.after, self.dirty = self.history.pop(), True

    def replay_row(self, row, column):
        if self.applied and self.applied[0] == 4 and 0 <= row < len(self.result_rows):
            self.pool.setCurrentIndex(list(POOLS).index(self.applied[1]))
            self.start.setText(self.applied[3])
            stamp = datetime.fromisoformat(self.result_rows[row]['finished']).astimezone(CHINA)
            self.replay.setText(stamp.strftime('%H:%M:%S.%f'))
            self.mode.setCurrentIndex(3)
            self.apply_filters()

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != (self.applied, self.after):
                self.scope.discard('limits', future)
            else:
                try:
                    result = self.scope.result('limits', future)
                    self.result_rows = result['rows']
                    fields, labels = FIELDS, LABELS
                    if self.applied[0] == 2:
                        fields = ('trade_date', 'unified_code', 'name', 'availability', 'reason_kind', 'reason_text')
                        labels = ('日期', '证券', '名称', '正文可用性', '原因分类', '来源原因正文')
                    elif self.applied[0] == 4:
                        fields = ('started', 'finished')
                        labels = ('开始采样（北京时间）', '采样完成（北京时间）')
                    self.table.setColumnCount(len(labels))
                    self.table.setHorizontalHeaderLabels(labels)
                    rows(self.table, [[POOLS.get(r.get(k), r.get(k)) if k == 'pool_type'
                        else display_value(k, r.get(k)) for k in fields] for r in result['rows']],
                        keys=[str(r.get('snapshot_id') or (r.get('trade_date'), r.get('pool_type'), r.get('unified_code')))
                              for r in result['rows']])
                    self.next_after = result['next']
                    self.status.setText(result['message'])
                    self.previous.setEnabled(bool(self.history))
                    self.following.setEnabled(self.next_after is not None)
                except Exception as exc:
                    self.status.setText(redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty = False
            self.requested = self.applied, self.after
            self.future = self.scope.invoke('limits', self.shell.runtime, 'yuanhang.limits.query',
                                            'browse', self.applied, self.after)

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
            self.mode.setCurrentIndex(1)
        if context.start:
            self.start.setText(context.start)
        if context.end:
            self.end.setText(context.end)
        self.apply_filters()


class LimitsUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang_limits', '远航涨跌停分析页面', provides=('ui.pages.yuanhang_limits',))

    def create_pages(self):
        return (PageContribution('yuanhang_limits', '远航涨跌停分析', LimitsPage, '数据浏览', 61,
            '涨停板、涨停冲刺、连板池、炸板池、跌停板及原因', catalogued=True, category='涨跌停分析',
            source='同花顺远航版', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS),
            management=NavigationTarget('collection', NavigationContext(task_id=project('limit_up_pool')))),)
