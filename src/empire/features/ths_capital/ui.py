"""Lazy, cursor-paged capital facts with full source details and release cards."""
from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.features.ths_capital.contract import PROJECT, SECTIONS, TABLE_SECTIONS, TABLES
from empire.features.ths_capital.contract import fields as definitions
from empire.plugins.ui.common import accessible, bind_find, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope

LABELS = dict(capital_funding='募集资金来源', capital_project='项目投资', capital_transaction='交易公告',
    capital_equity_summary='股权投资分类汇总', capital_equity_position='股权投资持仓', capital_ipo='参股IPO',
    capital_encumbrance='原质押/冻结', capital_release='解除事件')


def content(table, row):
    pairs = []
    for key, (label, kind) in definitions(table).items():
        if key in ('record_key', 'section'):
            continue
        value = row[key]
        value = '未知（来源未提供）' if value is None else '是' if kind == 'bool' and value else '否' if kind == 'bool' else str(value)
        pairs.append((label, value))
    pairs.append(('来源窗口', '当前页面列示' if row.get('in_window') else '历史已保存；当前页面未列示'))
    html = card(row['unified_code'] + ' · ' + (row['event_date'] or '来源无公告日期'), fields(pairs), LABELS[table])
    for child in row.get('releases', []):
        html += '<h3>关联解除</h3>' + content('capital_release', child)
    return html


class CapitalPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.applied, self.future, self.detail_future, self.dirty = None, None, None, True
        self.rows, self.selected = [], ''
        layout = QVBoxLayout(self)
        title = QLabel('公司资本运作（同花顺）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('金额按原币种，不自动折算；预计到期不等于实际解除。报告期不是公告日，历史记录不代表当前风险余额。'))
        bar = QHBoxLayout()
        self.kind = QComboBox()
        accessible(self.kind, '资本运作栏目')
        for table in TABLES:
            for section in TABLE_SECTIONS[table]:
                label = SECTIONS[section] + (' · ' + LABELS[table] if table in ('capital_equity_summary', 'capital_equity_position', 'capital_encumbrance', 'capital_release') else '')
                self.kind.addItem(label, (table, section))
        bar.addWidget(self.kind)
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label in ((self.code, '股票代码'), (self.start, '开始公告日/报告期 YYYY-MM-DD'), (self.end, '截止公告日/报告期 YYYY-MM-DD')):
            accessible(field, '资本运作' + label)
            field.setPlaceholderText(label)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        bind_find(self, self.code)
        find, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集任务')
        find.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id=PROJECT)))
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('读取已归档事实；首次使用请启用对应采集任务。')
        layout.addWidget(self.status)
        split = QSplitter()
        self.list = QListWidget()
        accessible(self.list, '资本运作记录列表')
        self.list.currentRowChanged.connect(self.choose)
        self.reader = CardReader('资本运作完整详情')
        split.addWidget(self.list)
        split.addWidget(self.reader)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)
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
        self.timer.start(300)
        self.find()

    def find(self):
        self.applied = (*self.kind.currentData(), *(f.text().strip() for f in (self.code, self.start, self.end)))
        self.after, self.history, self.dirty = None, [], True
        self.next_cursor = None
        self.previous.setEnabled(False)
        self.next.setEnabled(False)

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.next_cursor = None
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.dirty = True

    def spec(self):
        return (*self.applied, self.after, 20)

    def choose(self, index):
        self.selected = self.rows[index]['record_key'] if 0 <= index < len(self.rows) else ''
        if self.selected:
            table = self.applied[0]
            self.detail_future = (table, self.selected, self.scope.invoke('detail', self.shell.runtime,
                'ths_capital.query', 'detail', table, self.selected))

    def tick(self):
        if not self.isVisible():
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('browse', future)
                self.dirty = True
            else:
                try:
                    result = self.scope.result('browse', future)
                    self.rows, self.next_cursor = result['rows'], result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    self.list.blockSignals(True)
                    previous = self.selected
                    for i, r in enumerate(self.rows):
                        label = r['unified_code'] + ' · ' + (r['event_date'] or '无公告日期') + ' · ' + str(next((r[k] for k in ('target', 'project_name', 'holder', 'issue_type', 'investment_type') if r.get(k)), SECTIONS[r['section']]))
                        if i < self.list.count():
                            self.list.item(i).setText(label)
                        else:
                            self.list.addItem(label)
                    while self.list.count() > len(self.rows):
                        self.list.takeItem(self.list.count() - 1)
                    index = next((i for i, r in enumerate(self.rows) if r['record_key'] == previous), 0)
                    self.list.setCurrentRow(index if self.rows else -1)
                    self.list.blockSignals(False)
                    self.choose(index)
                    self.status.setText(f'本页{len(self.rows)}条；包含已保存历史，当前窗口状态见详情。')
                    if not self.rows:
                        self.reader.present('<p>此条件没有已归档记录；来源未提供、未采集和范围外须分别核查。</p>', identity=self.spec())
                except Exception as exc:
                    self.status.setText(redact(exc, self.shell.runtime.config))
        if self.detail_future and self.detail_future[2].done():
            table, key, future = self.detail_future
            self.detail_future = None
            if key == self.selected and table == self.applied[0]:
                try:
                    row = self.scope.result('detail', future)
                    if row:
                        self.reader.present(content(table, row), identity=(table, key))
                except Exception as exc:
                    self.status.setText(escape(redact(exc, self.shell.runtime.config)))
            else:
                self.scope.discard('detail', future)
        if self.dirty and self.future is None:
            self.dirty = False
            self.requested = self.spec()
            self.future = self.scope.invoke('browse', self.shell.runtime, 'ths_capital.query', 'browse', *self.requested)

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future = self.detail_future = None
        self.dirty = True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(kind=self.kind.currentIndex(), drafts=[f.text() for f in (self.code, self.start, self.end)],
                    applied=self.applied, after=self.after, history=self.history, selected=self.selected)

    def restore_ui_state(self, state):
        self.kind.setCurrentIndex(state['kind'])
        for f, value in zip((self.code, self.start, self.end), state['drafts'], strict=True):
            f.setText(value)
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], state['history']
        self.selected, self.dirty = state['selected'], True

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
            self.find()


class CapitalPageUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.ths_capital', '公司资本运作界面', provides=('ui.pages.ths_capital',))

    def create_pages(self):
        return (PageContribution('ths_capital', '公司资本运作', CapitalPage, '数据浏览', 51,
            '融资、募投、收购、投资、参股IPO、转让、关联交易及质押解冻', database_tables=TABLES,
            catalogued=True, category='公司行动', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
