"""Lazy source report cards with applied filters independent of editing drafts."""
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.features.performance.contract import UNIT_KINDS as KINDS
from empire.features.performance.contract import columns, project
from empire.plugins.ui.common import accessible, bind_find, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope

LABELS = {'unified_code': '证券', 'name': '名称', 'report_date': '报告期', 'announcement_date': '来源公告日期',
    'data_month': '数据月份', 'change_end': '变动截止日', 'change_start': '变动开始日',
    'actor': '变动人', 'price': '成交均价（元/股）', 'shares_changed': '变动数量（股）',
    'shares_after': '变动后持股（股）', 'reason': '变动原因', 'leader': '领导人姓名',
    'position': '职务', 'relationship': '与领导人关系', 'occurrence': '相同来源事实出现序号',
    'forecast_type': '预告类型', 'forecast_text': '预计范围（来源原文）', 'source_id': '来源公司编号',
    'source_date': '来源关联日期', 'profit_basis': '同比利润口径（来源代码）', 'profit_scope': '同比利润范围（来源代码）',
    'roe_scope': '同比ROE范围（来源代码）', 'net_profit': '净利润（元，按来源口径）', 'roe': 'ROE（%）', 'eps': 'EPS（元/股）',
    'assets': '总资产（元）', 'equity': '净资产（元）', 'comparison_value': '同比关联原值（元）',
    'previous_profit': '去年同期净利润（元）', 'previous_roe': '去年同期ROE（%）', 'profit_change': '利润变化（%）',
    'roe_change': 'ROE变化（%）', 'first_scheduled': '首次预约', 'changed_1': '第一次变更',
    'changed_2': '第二次变更', 'changed_3': '第三次变更', 'actual_date': '实际披露日期',
    'revenue': '营业收入（元）', 'previous_revenue': '去年同期营业收入（元）', 'operating_cashflow': '经营现金流净额（元）',
    'statistics_date': '统计日', 'holders': '股东户数（户）', 'average_float': '平均流通股（股/户）',
    'holder_change_pct': '户数变化（%）', 'top_float_shares': '前十大流通持股（股）', 'top_float_pct': '占流通股（%）',
    'top_shares': '前十大股东持股（股）', 'top_pct': '占总股本（%）', 'holder_change': '变化户数（户）'}


class PerformancePage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.applied, self.future, self.requested, self.dirty = ('', '', ''), None, None, True
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind][0] + '（通达信）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = ('数据日期按变动截止月份；公告日期单独保存，页面目录不代表全部历史。' if kind == 'shareholder_changes' else
                '统计日不是公布日；来源历史范围有限；原始股数以股展示。' if kind == 'holder_count' else
                '预约和实际披露分开；空日期保持未知。' if kind == 'earnings_disclosure' else
                '来源预计范围原文；不能把预告当实际利润。' if kind == 'earnings_forecast' else
                '快报同比口径并列保存；来源可能提前声明公告日，未来日期不表示信号已可用。' if kind == 'earnings_quick' else
                '金额以元展示；同比口径并列保存；不替代完整财务报表。')
        layout.addWidget(hint(note))
        bar = QHBoxLayout()
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label, placeholder in ((self.code, '证券', '六位代码或统一证券代码'),
                (self.start, '开始日期', '开始 YYYY-MM-DD'), (self.end, '截止日期', '截止 YYYY-MM-DD')):
            accessible(field, KINDS[kind][0] + label)
            field.setPlaceholderText(placeholder)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        bind_find(self, self.code)
        find, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集任务')
        find.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=project(kind))))
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('读取已归档记录…')
        layout.addWidget(self.status)
        self.reader = CardReader(KINDS[kind][0] + '阅读区')
        layout.addWidget(self.reader, 1)
        actions = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        actions.addWidget(self.previous)
        actions.addWidget(self.next)
        actions.addStretch()
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def find(self):
        self.applied = tuple(f.text().strip() for f in (self.code, self.start, self.end))
        self.after, self.next_cursor, self.history, self.dirty = None, None, [], True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def spec(self):
        return (*self.applied, self.after, 200)

    def tick(self):
        if not self.isVisible():
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('records', future)
                self.dirty = True
                return
            try:
                result = self.scope.result('records', future)
                self.next_cursor = result['next']
                self.previous.setEnabled(bool(self.history))
                self.next.setEnabled(bool(self.next_cursor))
                self.render(result['rows'])
                self.status.setText(f'本页{len(result["rows"])}条；结果只代表已归档数据，采集完整性见数据准备。')
            except Exception as exc:
                self.status.setText(redact(exc, self.shell.runtime.config))
        if self.dirty and self.future is None:
            self.dirty = False
            self.requested = self.spec()
            self.status.setText('读取已归档记录…')
            self.future = self.scope.invoke('records', self.shell.runtime, self.kind + '.tdx_query',
                                           'list_records', *self.requested)

    def render(self, records):
        from datetime import date, datetime
        html = ''
        for row in records:
            values = [(LABELS[k], row[k]) for k in columns(self.kind) if k not in ('name', 'unified_code')]
            if self.kind == 'earnings_disclosure':
                scheduled = next((row[k] for k in ('changed_3', 'changed_2', 'changed_1', 'first_scheduled') if row[k]), None)
                remaining = ('已披露' if row['actual_date'] else
                             str((date.fromisoformat(scheduled) - datetime.now(CHINA).date()).days) + '天' if scheduled else '未知')
                values.append(('当前剩余天数', remaining))
            html += card(row['unified_code'] + ' ' + (row['name'] or ''), fields(values), KINDS[self.kind][0])
        self.reader.present(html or '<p>当前条件无已归档数据；不能据此认定来源无记录。</p>', identity=self.spec())

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future = None
        self.dirty = True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(drafts=[f.text() for f in (self.code, self.start, self.end)], applied=self.applied,
                    after=self.after, history=self.history, position=self.reader.save_position())

    def restore_ui_state(self, state):
        for field, value in zip((self.code, self.start, self.end), state['drafts'], strict=True):
            field.setText(value)
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], state['history']
        self.reader.restore_position(state.get('position', 0))
        self.dirty = True

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
            self.find()


class PerformanceUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.tdx_' + kind, KINDS[kind][0] + '界面',
            provides=('ui.pages.tdx_' + kind,), description='按需创建的来源报告阅读与结构化查询')

    def create_pages(self):
        item = KINDS[self.kind]
        return (PageContribution(self.kind, item[0], partial(PerformancePage, kind=self.kind), '数据浏览', 50,
            '通达信财报解读；源端缺值与日期限制保持原值', database_tables=(item[1],),
            catalogued=True, category=item[3], source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
