"""Lazy listing browser, bounded pages and separately requested history text."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.listings import PROJECT, date_warning
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
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
from empire.plugins.ui.queries import QueryScope

FIELDS = ('unified_code', 'name', 'listing_date', 'establish_date', 'issuance_num', 'issuance_price',
          'first_day_open_price', 'issuance_pe', 'winning_rate', 'estimated_raised', 'actual_raised',
          'lead_underwriter', 'sponsor', 'detail_status')


class ListingPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.future = self.detail_future = None
        self.applied, self.requested, self.dirty = '', None, True
        self.selected = None
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
        layout.addWidget(self.table, 1)
        self.body = QTextBrowser()
        self.body.setMaximumHeight(180)
        self.body.setPlainText('选中证券后读取历史沿革；正文为来源当前版本。')
        layout.addWidget(self.body)
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
            self.body.setPlainText('正在读取历史沿革…')
            self.detail_future = self.scope.invoke('detail', self.shell.runtime, 'listings.query', 'detail', self.selected)

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
                    rows(self.table, [[('来源暂无（旧资料）' if r.get(k) == 'unavailable' else '有资料') if k == 'detail_status'
                        else r[k] if r[k] is not None else '' for k in FIELDS] for r in result['rows']],
                         keys=[r['unified_code'] for r in result['rows']])
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
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('listings', '查询失败', redact(exc, self.shell.cfg), stale=self.table.rowCount() > 0))
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            try:
                result = self.scope.result('detail', future)
                unavailable = (result or {}).get('detail_status') == 'unavailable'
                if unavailable:
                    result = result.get('last_valid') or {}
                warning = '来源日期警告：成立日晚于上市日，保留两项原值，不据成立日推算上市日。\n\n' if date_warning(result or {}) else ''
                if unavailable:
                    warning = '来源当前暂无发行资料；以下为上次有效资料，仅作历史参考。\n\n' + warning
                self.body.setPlainText(warning + ((result or {}).get('history') or '来源未提供历史沿革。'))
            except Exception as exc:
                self.body.setPlainText('历史沿革读取失败：' + redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('listings', self.shell.runtime, 'listings.query', 'list_records', *self.requested)

    def save_ui_state(self):
        return dict(code=self.code.text(), applied=self.applied, after=self.after, history=list(self.history),
                    table=table_identity_state(self.table))

    def restore_ui_state(self, state):
        self.code.setText(state['code'])
        self.applied, self.after, self.history = state['applied'], state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True


class ListingUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.listings', '上市与发行资料界面', provides=('ui.pages.listings',), description='按需创建上市资料与历史沿革查询')

    def create_pages(self):
        return (PageContribution('listings', '上市与发行资料', ListingPage, '数据浏览', 20,
            '首次上市日期、发行价格、募资及历史沿革', database_tables=('stock_listing',), catalogued=True,
            category='证券基础', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
