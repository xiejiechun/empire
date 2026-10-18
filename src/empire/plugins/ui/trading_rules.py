"""Independent lazy pages, cursor queries and on-demand official clause detail."""
from decimal import Decimal
from functools import partial
from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.trading_rules import KINDS, project
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import accessible, hint, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope

LABELS = {
    'SH': '上海', 'SZ': '深圳', 'BJ': '北京', 'CN': '全国',
    'MAIN': '主板', 'STAR': '科创板', 'CHINEXT': '创业板', 'ALL': '全部板块',
    'ordinary': '普通交易', 'exemptions': '涨跌幅豁免', 'unknown_minimum': '最低收费未明确',
    'limit_ratio': '涨跌幅比例', 'rounding': '价格舍入',
    'resale_constraint': '买入后卖出限制', 'buy_minimum': '最低买入数量',
    'buy_increment': '买入递增数量', 'odd_lot': '零股卖出',
    'star_orders': '科创板数量限制', 'maximum': '最大申报数量',
    'price_tick': '最小价格变动', 'open_auction': '开盘集合竞价',
    'continuous_am': '上午连续竞价', 'continuous_pm': '下午连续竞价',
    'close_auction': '收盘集合竞价', 'after_hours': '盘后固定价格交易',
    'buy_rate': '买方税费率', 'sell_rate': '卖方税费率',
    'basis': '计费基数', 'minimum': '最低收费',
    'ratio': '%', 'shares': '股', 'CNY': '元', 'Asia/Shanghai': '北京时间', 'text': '说明',
}


def display_value(row, key):
    value = row[key]
    if value is None:
        return '未明确' if key == 'effective_end' else ''
    if key == 'number_value' and row['unit'] == 'ratio':
        percent = format(Decimal(value) * 100, 'f')
        return percent.rstrip('0').rstrip('.') if '.' in percent else percent
    if key in ('market', 'board', 'condition_key', 'parameter_key', 'unit'):
        return LABELS.get(value, value)
    return value


class RulePage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.after, self.next_cursor, self.history = None, None, []
        self.future, self.detail_future, self.dirty = None, None, True
        self.requested = self.selected_key = None
        layout = QVBoxLayout(self)
        title = QLabel(KINDS[kind])
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('已归档官方条款及参数；选择一行查看依据。当前规则不代表整个历史已准备完成，详细缺口见数据准备检查。'))
        bar = QHBoxLayout()
        self.market = accessible(QComboBox(), '交易规则市场')
        self.market.addItems(['全部', 'SH', 'SZ', 'BJ', 'CN'])
        self.market.currentIndexChanged.connect(self.find)
        bar.addWidget(self.market)
        for label, callback in [('查询 / 刷新', self.find), ('管理采集任务', lambda: shell.navigate('collection', NavigationContext(task_id=project(kind))))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.status = hint('正在查询…')
        layout.addWidget(self.status)
        self.table = table(['市场', '板块', '条件', '参数', '生效', '终止', '数值', '单位', '开始时间', '结束时间', '说明'])
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table, 1)
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(True)
        layout.addWidget(self.reader, 1)
        self.values = []
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
        self.after, self.history, self.next_cursor, self.dirty = None, [], None, True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def spec(self):
        return self.market.currentText() if self.market.currentIndex() else '', self.after

    def select(self):
        index = self.table.currentRow()
        key = self.values[index]['citation_key'] if 0 <= index < len(self.values) else None
        if key != self.selected_key:
            self.selected_key = key
            self.reader.setPlainText('正在读取官方依据…' if key else '请选择规则参数')
            if key:
                self.detail_future = self.scope.invoke('citation', self.shell.runtime, 'rules.' + self.kind + '.query', 'citation', key)

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('rules', future)
            else:
                try:
                    result = self.scope.result('rules', future)
                    self.values, self.next_cursor = result['rows'], result['next']
                    rows(self.table, [[display_value(r, k) for k in ('market', 'board', 'condition_key', 'parameter_key', 'effective_start', 'effective_end', 'number_value', 'unit', 'start_time', 'end_time', 'text_value')] for r in self.values], keys=[r['record_key'] for r in self.values])
                    self.select()
                    self.status.setText(f'第{len(self.history)+1}页，本页{len(self.values)}条；每页最多200条')
                    self.previous.setEnabled(bool(self.history))
                    self.next.setEnabled(bool(self.next_cursor))
                except Exception as exc:
                    self.status.setText('查询失败：' + redact(exc, self.shell.cfg))
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            try:
                value = self.scope.result('citation', future)
                if value and value['citation_key'] == self.selected_key:
                    self.reader.setHtml('<h3>' + escape(value['title']) + '</h3><p>' + escape(value['issuer'] + ' · ' + value['published_date'] + ' · ' + value['clause_key']) + '</p><p>' + escape(value['excerpt']) + '</p><a href="' + escape(value['source_url'], quote=True) + '">打开官方依据</a>')
            except Exception as exc:
                self.reader.setPlainText('依据查询失败：' + redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('rules', self.shell.runtime, 'rules.' + self.kind + '.query', 'list_rules', *self.requested)


class RuleUiPlugin(UiPlugin):
    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.rules_' + kind, KINDS[kind] + '界面', provides=('ui.pages.rules_' + kind,))

    def create_pages(self):
        return (PageContribution('rules_' + self.kind, KINDS[self.kind], partial(RulePage, kind=self.kind),
            '数据浏览', 20, '规则生效段、数值及官方依据', database_tables=('trading_rule_value', 'trading_rule_citation'),
            catalogued=True, category='交易费用' if self.kind in ('stamp_duty', 'transfer_fee') else '交易规则',
            source='官方规则', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
