"""Lazy report selection and ranked holder cards, with separate exited records."""
from decimal import Decimal
from functools import partial
from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
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
from empire.features.holders.contract import KINDS, project, quality_details
from empire.plugins.ui.common import accessible, bind_find, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope


def shown(value, scale, digits, kind):
    if value is None:
        return '未知（来源未提供）'
    unit = '张' if kind == 'bond_holders' else '股'
    suffix = {1: '', 10000: '万', 100000000: '亿'}[scale]
    return f'{Decimal(value) / scale:.{digits}f}' + suffix + unit


class HolderPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.applied, self.future, self.requested, self.dirty = ('', '', ''), None, None, True
        self.details, self.selected, self.rows = None, '', []
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind][0] + '（同花顺）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('报告期不是公告日；当前窗口之外不代表没有记录。数量保持来源舍入精度，退出名单为上期参考。'))
        bar = QHBoxLayout()
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label, placeholder in ((self.code, '股票', '股票代码或统一代码'),
                (self.start, '开始报告期', '开始 YYYY-MM-DD'), (self.end, '截止报告期', '截止 YYYY-MM-DD')):
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
        self.status = hint('读取已归档报告…')
        layout.addWidget(self.status)
        split = QSplitter()
        self.reports = QListWidget()
        accessible(self.reports, KINDS[kind][0] + '报告列表')
        self.reports.currentRowChanged.connect(self.choose)
        self.reader = CardReader(KINDS[kind][0] + '名单阅读区')
        split.addWidget(self.reports)
        split.addWidget(self.reader)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)
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
        return (*self.applied, self.after, 20)

    def choose(self, index):
        self.selected = self.rows[index]['report_key'] if 0 <= index < len(self.rows) else ''
        if self.selected:
            self.details = (self.selected, self.scope.invoke('detail', self.shell.runtime,
                self.kind + '.query', 'detail', self.selected))

    def tick(self):
        if not self.isVisible():
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('reports', future)
                self.dirty = True
            else:
                try:
                    result = self.scope.result('reports', future)
                    self.next_cursor = result['next']
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                    selected = self.selected
                    self.reports.blockSignals(True)
                    self.reports.clear()
                    self.rows = result['rows']
                    for r in self.rows:
                        self.reports.addItem(r['unified_code'] + ' · ' + r['report_date'] +
                            (' · 变动公告（非完整前十）' if r['report_type'] == 'change_notice' else '') +
                            (' · ' + r['instrument_name'] if self.kind == 'bond_holders' else '') +
                            (' · 来源质量异常' if r['quality_flags'] else ''))
                    index = next((i for i, r in enumerate(self.rows) if r['report_key'] == selected), 0)
                    self.reports.setCurrentRow(index if self.rows else -1)
                    self.reports.blockSignals(False)
                    self.choose(index)
                    self.status.setText(f'本页{len(self.rows)}份已归档报告；来源窗口覆盖见数据准备。')
                    if not self.rows:
                        self.reader.present('<p>当前条件没有已归档报告；栏目未提供、未采集或窗口外须分别核查。</p>', identity=self.spec())
                except Exception as exc:
                    self.status.setText(redact(exc, self.shell.runtime.config))
        if self.details and self.details[1].done():
            key, future = self.details
            self.details = None
            if key == self.selected:
                try:
                    report = self.scope.result('detail', future)
                    if report:
                        self.render(report)
                except Exception as exc:
                    self.status.setText(redact(exc, self.shell.runtime.config))
            else:
                self.scope.discard('detail', future)
        if self.dirty and self.future is None:
            self.dirty = False
            self.requested = self.spec()
            self.future = self.scope.invoke('reports', self.shell.runtime, self.kind + '.query', 'browse', *self.requested)

    def render(self, report):
        notice = report['report_type'] == 'change_notice'
        amount = '未知（来源未提供）' if report['total_quantity'] is None else shown(report['total_quantity'], report['total_quantity_scale'], report['total_quantity_decimals'], self.kind)
        content = card(report['report_date'] + ' · ' + report['instrument_name'], fields([
            ('来源类型', '主要股东持股变动公告（名单可能超过或少于十人）' if notice else '报告期前十大名单'),
            ('累计持有', amount), ('累计比例', report['total_ratio'] + '%' if report['total_ratio'] is not None else '未知（来源未提供）'), ('比例口径', report['ratio_basis'])]), KINDS[self.kind][0])
        issues = quality_details(report)
        if issues:
            content += '<h3>来源质量异常</h3><p>已保留来源实际列示名单与原值，不能据此证明业务前十完整或数值一致。</p>'
            content += fields([(issue['reason'], ('来源 ' + ('未知' if issue['source'] is None else str(issue['source'])) + '；已知明细合计 ' + issue['known_sum'])
                               if 'known_sum' in issue else issue.get('detail') or str(issue['unknown_members']) + '位当期持有人比例未知') for issue in issues])
        for group, label in (('current', '本次公告列示持有人' if notice else '来源当期列示名单' if issues else '当期前十大'), ('exited', '较上期退出（上期数值）')):
            members = [m for m in report['members'] if m['member_group'] == group]
            if not members:
                continue
            content += '<h3>' + escape(label) + '</h3>'
            if group == 'current' and [m['source_rank'] or m['seq'] for m in members] != list(range(1, len(members) + 1)):
                content += '<p>来源排名存在并列或缺口；仅保留页面实际列示记录，未补造缺失持有人。</p>'
            for m in members:
                content += card(f"{m['source_rank'] or m['seq']}. {m['holder_name']}", fields([
                    ('持有数量', shown(m['quantity'], m['quantity_scale'], m['quantity_decimals'], self.kind)),
                    ('持有比例', m['ratio'] + '%' if m['ratio'] is not None else '未知（来源未提供）'), ('股份类型', m['share_type']),
                    ('数量变化', m['change_quantity'] if m['change_label'] == 'numeric' else
                     {'unchanged': '不变', 'new': '新进', 'exited': '退出', 'unknown': '未知'}.get(m['change_label'])),
                    ('来源实际增减/变动比例', m['actual_change']), ('质押占直接持股比', m['pledge_status'])]), '')
        self.reader.present(content, identity=self.selected)

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future = self.details = None
        self.dirty = True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(drafts=[f.text() for f in (self.code, self.start, self.end)], applied=self.applied,
                    after=self.after, history=self.history, selected=self.selected)

    def restore_ui_state(self, state):
        for field, value in zip((self.code, self.start, self.end), state['drafts'], strict=True):
            field.setText(value)
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], state['history']
        self.selected, self.dirty = state.get('selected', ''), True

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
            self.find()


class HolderUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.' + kind,))

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], partial(HolderPage, kind=self.kind), '数据浏览', 50,
            '当前报告期前十及退出名单；来源舍入、无公告日期', database_tables=('holder_report', 'holder_member'),
            catalogued=True, category='股东数据', source='同花顺', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
