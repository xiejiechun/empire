"""Lazy paged plan overview with an independently loaded selected-plan reader."""
import html

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.repurchases import PROGRESS, PROJECT
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import (
    accessible,
    hint,
    restore_table_identity,
    rows,
    table,
    table_identity_state,
)
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


def shown(value, unit=''):
    return '来源未提供' if value is None else str(value) + unit


def interval(row, prefix, unit):
    return shown(row[prefix + '_lower'], unit) + ' ～ ' + shown(row[prefix + '_upper'], unit)


class RepurchasePage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.history, self.next_cursor = None, [], None
        self.future = self.detail_future = None
        self.requested = self.detail_requested = None
        self.selected, self.data = '', []
        self.applied, self.dirty = ('', '', '', ''), True
        layout = QVBoxLayout(self)
        title = QLabel('股票回购（东方财富）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('查看回购方案与累计进展；金额为元、数量为股。回购完成不代表已注销，当前修订不能还原历史信号。'))
        bar = QHBoxLayout()
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label, placeholder in ((self.code, '证券代码', '证券代码或前缀'),
                (self.start, '起始方案公告日', '起始 YYYY-MM-DD'), (self.end, '截止方案公告日', '截止 YYYY-MM-DD')):
            accessible(field, label)
            field.setPlaceholderText(placeholder)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        self.code.setMaxLength(9)
        self.progress = accessible(QComboBox(), '回购实施状态')
        self.progress.addItem('全部实施状态', '')
        for code in ('001', '002', '003', '004', '005', '006', '007', '008'):
            self.progress.addItem(PROGRESS.get(code, '来源状态 ' + code), code)
        bar.addWidget(self.progress)
        find, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集')
        find.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=PROJECT)))
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('正在读取已归档方案…')
        layout.addWidget(self.status)
        self.table = table(['证券', '方案公告日', '来源状态', '计划金额（元）', '已回购数量（股）', '已回购金额（元）', '最新公告日'])
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.previous, self.next = QPushButton('上一页'), QPushButton('下一页')
        self.previous.clicked.connect(lambda: self.move(False))
        self.next.clicked.connect(lambda: self.move(True))
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch()
        layout.addLayout(bar)
        self.reader = QTextBrowser()
        self.reader.setMinimumHeight(170)
        self.reader.setHtml('<p>选择一份方案，查看计划、实际回购和来源说明。</p>')
        layout.addWidget(self.reader, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def find(self):
        self.scope.cancel('detail')
        self.detail_future = self.detail_requested = None
        self.applied = (self.code.text().strip(), self.start.text().strip(), self.end.text().strip(), self.progress.currentData())
        self.after, self.history, self.next_cursor, self.dirty = None, [], None, True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def select(self):
        index = self.table.currentRow()
        ident = self.data[index]['plan_id'] if 0 <= index < len(self.data) else ''
        if ident != self.selected:
            self.selected = ident
            self.reader.setHtml('<p>正在读取方案详情…</p>' if ident else '<p>选择方案查看详情。</p>')

    def render_detail(self, r):
        if not r:
            self.reader.setPlainText('方案未找到。')
            return
        lines = [f'<h3>{html.escape(r["name"])} · {r["unified_code"]} · 方案 {r["plan_id"]}</h3>']
        for label, value in (
                ('初始方案公告日', shown(r['plan_date'])), ('实施状态', PROGRESS.get(r['progress_code'], '来源状态 '+r['progress_code'])),
                ('计划金额', interval(r, 'plan_amount', '元')), ('计划数量', interval(r, 'plan_quantity', '股')),
                ('计划价格', interval(r, 'plan_price', '元/股')), ('回购期限', shown(r['start_date'])+' ～ '+shown(r['end_date'])),
                ('累计实际回购', shown(r['actual_quantity'], '股')+'；'+shown(r['actual_amount'], '元')),
                ('实际回购价格', interval(r, 'actual_price', '元/股')), ('统计截止日 / 公告日', shown(r['actual_through'])+' / '+shown(r['notice_date'])),
                ('回购完成日', shown(r['finish_date'])), ('来源更新日', shown(r['updated_date'])),
                ('回购用途', shown(r['objective'])), ('方案说明', shown(r['remark'])), ('进展说明', shown(r['progress_remark']))):
            lines.append('<p><b>'+html.escape(label)+'</b><br>'+html.escape(value).replace('\n', '<br>')+'</p>')
        lines.append('<p>来源的完成日、回购用途均不能替代股份注销生效日。</p>')
        self.reader.setHtml(''.join(lines))

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        spec = (*self.applied, self.after, 200)
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != spec:
                self.scope.discard('plans', future)
            else:
                try:
                    result = self.scope.result('plans', future)
                    self.data = result['rows']
                    rows(self.table, [[r['name']+' '+r['unified_code'], r['plan_date'],
                        PROGRESS.get(r['progress_code'], r['progress_code']), interval(r, 'plan_amount', ''),
                        shown(r['actual_quantity']), shown(r['actual_amount']), shown(r['notice_date'])] for r in self.data],
                        keys=[r['plan_id'] for r in self.data])
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.status.setText(f'第{len(self.history)+1}页，本页{len(self.data)}方案；点击查看详情。')
                    self.select()
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('plans', '查询失败', redact(exc, self.shell.cfg), stale=bool(self.data)))
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            if self.detail_requested != self.selected:
                self.scope.discard('detail', future)
                self.detail_requested = None
            else:
                try:
                    self.render_detail(self.scope.result('detail', future))
                except Exception as exc:
                    self.reader.setPlainText('详情查询失败：'+redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, spec
            self.future = self.scope.invoke('plans', self.shell.runtime, 'repurchases.query', 'list_plans', *spec)
        if self.isVisible() and self.selected and self.selected != self.detail_requested and not self.detail_future:
            self.detail_requested = self.selected
            self.detail_future = self.scope.invoke('detail', self.shell.runtime, 'repurchases.query', 'detail', self.selected)

    def apply_navigation_context(self, context):
        self.code.setText(context.unified_code)
        self.start.setText(context.start)
        self.end.setText(context.end)
        self.find()

    def save_ui_state(self):
        return dict(code=self.code.text(), start=self.start.text(), end=self.end.text(), progress=self.progress.currentIndex(),
                    applied=self.applied, after=self.after, history=self.history, table=table_identity_state(self.table))

    def restore_ui_state(self, state):
        for key in ('code', 'start', 'end'):
            getattr(self, key).setText(state[key])
        self.progress.setCurrentIndex(state['progress'])
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], list(state['history'])
        restore_table_identity(self.table, state['table'])
        self.dirty = True


class RepurchaseUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.repurchases', '股票回购界面', provides=('ui.pages.repurchases',), description='按需创建回购方案与详情')

    def create_pages(self):
        return (PageContribution('repurchases', '股票回购', RepurchasePage, '数据浏览', 30,
            '计划与累计回购；不推断股份注销', database_tables=('stock_repurchase_plan',), catalogued=True,
            category='公司行动', source='东方财富', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
