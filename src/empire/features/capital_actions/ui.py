"""Independent lazy views for the three capital-action datasets."""
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.capital_actions.contract import KINDS
from empire.features.capital_actions.preview import plan_cards, plan_profile
from empire.features.capital_actions.words import LABELS
from empire.features.data_browser.search import CandidateSearch
from empire.plugins.ui.common import (
    accessible,
    bind_find,
    hint,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader
from empire.plugins.ui.preview_layout import DataNote, DetailSplit, QueryForm
from empire.plugins.ui.preview_navigation import security_context
from empire.plugins.ui.queries import QueryScope


class CapitalPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind = shell, kind
        self.query_scope = QueryScope(self)
        self.page, self.records = 0, []
        self.future = self.requested = None
        self.dirty = True
        self.applied = ('', '', '', '', '')
        self.event_key = ''
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind][0])
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(DataNote('通达信 · 已归档方案 · 缺失日期和数值为未知。',
            '金额/比例为每股，股数按来源值；分红按除息日记账。增发/配股来源未提供公告时间，不用于公告前选股。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), '证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('证券代码（支持前缀）')
        self.code.setClearButtonEnabled(True)
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.search)
        self.candidates = CandidateSearch(self, self.code, shell, kind, self.choose_security)
        bar.addWidget(self.code)
        self.market = QComboBox()
        self.market.addItem('全部市场', '')
        for market in ('SH', 'SZ', 'BJ'):
            self.market.addItem(market, market)
        bar.addWidget(self.market)
        refresh = QPushButton('查询 / 刷新')
        refresh.clicked.connect(self.search)
        bar.addWidget(refresh)
        manage = QPushButton('管理采集计划')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=KINDS[kind][2])))
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.start, self.end, self.plan_status = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label in ((self.start, '开始日期 YYYY-MM-DD'), (self.end, '截止日期 YYYY-MM-DD'), (self.plan_status, '来源方案状态（精确匹配）')):
            field.setPlaceholderText(label + '；空=不限')
            accessible(field, label)
            field.returnPressed.connect(self.search)
        date_role = {'dividends': '除息日（缺失时报告期）', 'additional_issues': '发行日（缺失时上市日）',
                     'rights_issues': '除权日'}[kind]
        layout.addWidget(QueryForm([(date_role + '起', self.start), (date_role + '止', self.end),
                                   ('来源方案状态', self.plan_status)]))
        self.status = hint('正在查询……')
        layout.addWidget(self.status)
        self.table = table(['证券代码', '名称', '报告期 / 发行 / 除权日期', '方案进度 / 类型'])
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.views = QTabWidget()
        self.cards = CardReader('增发送配方案摘要')
        self.cards.selected.connect(self.select_plan)
        self.views.addTab(self.cards, '方案列表')
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(self.table, 1)
        self.views.addTab(details, '检索明细')
        self.distribution = None
        if kind == 'dividends':
            from empire.features.capital_actions.ui_distribution import DistributionPanel
            self.distribution = DistributionPanel(self)
            self.views.addTab(self.distribution, '名义派息汇总')
        self.profile = CardReader('所选方案档案与关键日期')
        self.splitter = DetailSplit(self.views, self.profile, '方案与关键日期')
        layout.addWidget(self.splitter, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        details_layout.addWidget(self.detail, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def spec(self):
        return (*self.applied[:2], 51, self.page * 50, *self.applied[2:], self.event_key)

    def search(self):
        self.event_key = ''
        self.applied = (self.code.text().strip(), self.market.currentData(), self.start.text().strip(), self.end.text().strip(), self.plan_status.text().strip())
        self.page = 0
        self.reload()

    def move(self, step):
        self.page = max(0, self.page + step)
        self.reload()

    def reload(self):
        self.query_scope.cancel('events')
        self.future = None
        self.dirty = True
        self.tick()

    def render(self, result):
        self.records = result[:50]
        self.cards.present(plan_cards(self.kind, self.records), identity=(self.applied, self.page))
        rows(self.table, [[r['code'], r['name'], r['event_date'] or '来源未提供',
                          r['data'].get('issue_method', r['data']['status'])] for r in self.records],
             keys=[r['record_key'] for r in self.records])
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(len(result) > 50)
        self.status.setText(f'第 {self.page + 1} 页 · {len(self.records)} 条；无记录不代表已完成采集')
        if self.records and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.show_detail()

    def show_detail(self):
        index = self.table.currentRow()
        if not 0 <= index < len(self.records):
            self.detail.clear()
            self.profile.present('<p>选择方案查看日期、数值和来源状态。</p>')
            return
        r = self.records[index]
        self.profile.present(plan_profile(self.kind, r), identity=r['record_key'])
        values = {k: v for k, v in r['data'].items() if k != 'detail'}
        if self.kind == 'additional_issues':
            detail = r['data'].get('detail')
            if detail and detail.get('availability') == 'unavailable':
                values['详情状态'] = '来源暂无可用详情'
                values['来源接口状态'] = '返回空详情' if detail['source_error_code'] == 0 else '-1005（数据库执行失败）'
                if detail.get('last_available'):
                    values['历史参考说明'] = '以下保留上次有效明细，不代表来源本次提供的数据'
                    values.update(detail['last_available'])
            else:
                values.update(detail or {'详情采集': '尚未补齐，请继续采集'})
        self.detail.setPlainText(r['market'] + ' ' + r['code'] + ' ' + r['name'] + '\n' + '\n'.join(
            f"{LABELS.get(k, k)}：{v if v is not None else '来源未提供'}" for k, v in values.items()))

    def select_plan(self, index):
        self.table.selectRow(index)
        self.show_detail()
        self.splitter.show_detail()

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.distribution is not None:
            self.distribution.tick()
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.query_scope.discard('events', future)
            else:
                try:
                    self.render(self.query_scope.result('events', future))
                except Exception as exc:
                    self.status.setText(self.query_scope.failure_message('events', '查询失败',
                        redact(exc, self.shell.cfg), stale=bool(self.records)))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty = False
            self.requested = self.spec()
            self.future = self.query_scope.invoke('events', self.shell.runtime,
                self.kind + '.query', 'list_events', *self.requested)

    def save_ui_state(self):
        return {'code': self.code.text(), 'page': self.page, 'market': self.market.currentData(),
                'applied': self.applied, 'view': self.views.currentIndex(), 'event_key': self.event_key,
                'drafts': (self.start.text(), self.end.text(), self.plan_status.text()),
                'table': table_identity_state(self.table), 'position': self.cards.save_position(),
                'profile_position': self.profile.save_position()}

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.page = state['page']
        self.dirty = True
        self.market.setCurrentIndex(max(0, self.market.findData(state.get('market', ''))))
        self.applied = tuple(state.get('applied', (self.code.text(), '')))
        self.splitter.restore_view(state.get('view', 0))
        self.event_key = state.get('event_key', '')
        if 'table' in state:
            restore_table_identity(self.table, state['table'])
        self.cards.restore_position(state.get('position', 0))
        self.profile.restore_position(state.get('profile_position', 0))
        for field, value in zip((self.start, self.end, self.plan_status), state.get('drafts', ('', '', '')), strict=True):
            field.setText(value)

    def choose_security(self, record):
        self.market.setCurrentIndex(self.market.findData(record['unified_code'][-2:]))

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.code.setText(code)
        self.market.setCurrentIndex(self.market.findData(market))
        self.search()
        if context.event_key:
            self.event_key = context.event_key
            self.applied = (code, market, '', '', '')
            self.reload()

class CapitalUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面',
            provides=('ui.pages.' + kind,), description='独立按需创建的通达信方案浏览')

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], partial(CapitalPage, kind=self.kind),
            '数据浏览', 4 + list(KINDS).index(self.kind), '通达信历史方案与证券关联',
            database_tables=(KINDS[self.kind][1],),
            catalogued=True, category='增发送配', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=KINDS[self.kind][2]))),)
