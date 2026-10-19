"""Lazy listing browser, bounded pages and separately requested history text."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.listings import PROJECT, date_warning
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
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
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.preview_layout import compact_columns, fit_directory
from empire.plugins.ui.preview_navigation import security_context
from empire.plugins.ui.queries import QueryScope

FIELDS = ('unified_code', 'name', 'listing_date', 'establish_date', 'issuance_num', 'issuance_price',
          'first_day_open_price', 'issuance_pe', 'winning_rate', 'estimated_raised', 'actual_raised',
          'lead_underwriter', 'sponsor', 'detail_status')
STATUS = {'available': '有资料', 'unavailable': '来源暂无（旧资料）', 'incomplete': '缺上市日期（旧资料）'}


class ListingPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.future = self.detail_future = None
        self.applied, self.requested, self.dirty = '', None, True
        self.selected = None
        self.records = []
        layout = QVBoxLayout(self)
        title = QLabel('上市与发行资料（同花顺）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('上市日期为来源首次上市日；数量为股，价格及募资为元，中签率为百分数。空白表示来源未知；不提供全部退市证券或重新上市历史。'))
        bar = QHBoxLayout()
        self.code = accessible(QLineEdit(), '上市证券代码')
        self.code.setMaxLength(6)
        self.code.setPlaceholderText('六位代码或前缀')
        bind_find(self, self.code)
        self.code.returnPressed.connect(self.find)
        self.candidates = CandidateSearch(self, self.code, shell, 'listings', self.choose_security)
        bar.addWidget(self.code)
        find = QPushButton('查询 / 刷新')
        find.clicked.connect(self.find)
        bar.addWidget(find)
        manage = QPushButton('管理采集任务')
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=PROJECT)))
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('正在读取已归档上市记录…')
        layout.addWidget(self.status)
        self.table = table(['证券', '当前名称', '上市日期', '成立日期', '发行数量(股)', '发行价(元)',
            '首日开盘(元)', '发行市盈率', '中签率(%)', '预计募资(元)', '实际募资(元)', '主承销商', '保荐人', '来源资料状态'])
        self.table.itemSelectionChanged.connect(self.select)
        compact_columns(self.table, (105, 140, 105), 1)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        self.views = QTabWidget()
        self.profile = CardReader('上市发行资料档案')
        self.views.addTab(self.profile, '上市与发行')
        self.body = QTextBrowser()
        self.body.setPlainText('选中证券后读取历史沿革；正文为来源当前版本。')
        self.views.addTab(self.body, '历史沿革')
        self.splitter.addWidget(self.views)
        self.splitter.setSizes([240, 800])
        for column in range(3, len(FIELDS)):
            self.table.hideColumn(column)
        layout.addWidget(self.splitter, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def find(self):
        self.applied, self.after, self.history = self.code.text().strip(), None, []
        self.next_cursor, self.dirty = None, True
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.clear_detail()

    def clear_detail(self):
        self.scope.cancel('detail')
        self.detail_future, self.selected = None, None
        self.body.setPlainText('选中证券后读取历史沿革；正文为来源当前版本。')

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True
        self.clear_detail()

    def select(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            self.selected = item.text()
            self.render_profile()
            self.body.setPlainText('正在读取历史沿革…')
            self.detail_future = self.scope.invoke('detail', self.shell.runtime, 'listings.query', 'detail', self.selected)

    def render_profile(self):
        record = next((r for r in self.records if r['unified_code'] == self.selected), None)
        if not record:
            self.profile.present('<p>选择一只证券查看上市资料。</p>')
            return
        labels = dict(zip(FIELDS, ['证券', '当前名称', '首次上市日', '成立日', '发行数量（股）',
            '发行价（元）', '首日开盘（元）', '发行市盈率', '中签率（%）', '预计募资（元）',
            '实际募资（元）', '主承销商', '保荐人', '资料状态'], strict=True))
        body = fields([(labels[k], STATUS.get(record[k], record[k]) if k == 'detail_status' else record[k])
                       for k in FIELDS[2:]])
        if date_warning(record):
            body = '<p>来源日期有矛盾：成立日晚于上市日，两项原值均保留。</p>' + body
        self.profile.present(card(record['name'], body, record['unified_code']), identity=self.selected)

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.code.setText(code + '.' + market)
        self.target_security = code + '.' + market
        self.find()

    def choose_security(self, record):
        self.code.setText(record['unified_code'])
        self.target_security = record['unified_code']
        self.find()

    def resizeEvent(self, event):
        self.splitter.setOrientation(Qt.Orientation.Vertical if self.width() < 780 else Qt.Orientation.Horizontal)
        self.table.setMaximumHeight(16777215 if self.width() >= 780 else 170)
        if self.width() < 780:
            fit_directory(self.table, self.records)
        super().resizeEvent(event)

    def spec(self):
        return self.applied, '', '', self.after, 200

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('listings', future)
            else:
                try:
                    result = self.scope.result('listings', future)
                    self.records = result['rows']
                    if self.width() < 780:
                        fit_directory(self.table, self.records)
                    rows(self.table, [[STATUS.get(r.get(k), r.get(k)) if k == 'detail_status'
                        else r[k] if r[k] is not None else '' for k in FIELDS] for r in result['rows']],
                         keys=[r['unified_code'] for r in result['rows']])
                    if self.records:
                        preferred = getattr(self, 'target_security', self.selected)
                        self.table.selectRow(next((i for i, r in enumerate(self.records)
                            if r['unified_code'] == preferred), 0))
                        self.select()
                    else:
                        self.clear_detail()
                        self.profile.present('<p>该范围暂无已归档上市资料。</p>')
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'第{len(self.history)+1}页，本页{len(result["rows"])}条；每页最多200条。')
                    conflicts = sum(date_warning(r) for r in result['rows'])
                    if conflicts:
                        self.status.setText(self.status.text() + f' 来源成立日晚于上市日{conflicts}条，原值保留。')
                    unavailable = result.get('unavailable_count', 0)
                    if unavailable:
                        self.status.setText(self.status.text() + f' 来源暂无资料{unavailable}只；无有效资料者不生成上市记录。')
                        if not result['rows']:
                            self.body.setPlainText('来源明确暂无发行资料；稍后自动复查，不推断退市或填造上市日期。')
                    incomplete = result.get('incomplete_count', 0)
                    if incomplete:
                        self.status.setText(self.status.text() + f' 来源缺上市日期{incomplete}只；后续自动补查，不能推断未上市。')
                        if not result['rows']:
                            self.body.setPlainText('来源成功返回发行资料，但缺必需上市日期；未生成上市记录，不用成立日填补。数据准备仍未通过。')
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('listings', '查询失败', redact(exc, self.shell.cfg), stale=self.table.rowCount() > 0))
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            try:
                result = self.scope.result('detail', future)
                availability = (result or {}).get('detail_status')
                unusable = availability in ('unavailable', 'incomplete')
                if unusable:
                    result = result.get('last_valid') or {}
                warning = '来源日期警告：成立日晚于上市日，保留两项原值，不据成立日推算上市日。\n\n' if date_warning(result or {}) else ''
                if unusable:
                    reason = '来源缺必需上市日期' if availability == 'incomplete' else '来源当前暂无发行资料'
                    warning = reason + '；以下为上次有效资料，仅作历史参考。\n\n' + warning
                self.body.setPlainText(warning + ((result or {}).get('history') or '来源未提供历史沿革。'))
                if hasattr(self, 'body_position'):
                    self.body.verticalScrollBar().setValue(self.body_position)
                    del self.body_position
            except Exception as exc:
                self.body.setPlainText('历史沿革读取失败：' + redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('listings', self.shell.runtime, 'listings.query', 'list_records', *self.requested)

    def save_ui_state(self):
        return dict(code=self.code.text(), applied=self.applied, after=self.after, history=list(self.history),
                    table=table_identity_state(self.table), view=self.views.currentIndex(),
                    profile_position=self.profile.save_position(), body_position=self.body.verticalScrollBar().value())

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.applied, self.after, self.history = state['applied'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True
        self.views.setCurrentIndex(state.get('view', 0))
        self.profile.restore_position(state.get('profile_position', 0))
        self.body_position = state.get('body_position', 0)


class ListingUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.listings', '上市与发行资料界面', provides=('ui.pages.listings',), description='按需创建上市资料与历史沿革查询')

    def create_pages(self):
        return (PageContribution('listings', '上市与发行资料', ListingPage, '数据浏览', 20,
            '首次上市日期、发行价格、募资及历史沿革', database_tables=('stock_listing',), catalogued=True,
            category='证券基础', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
