"""Lazy review page with explicit filter application and cancellable reads."""
from datetime import datetime, timedelta

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.features.market_review.views import METRICS, build_tables, chart, render, value
from empire.plugins.ui.common import accessible
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import DataNote, QueryForm
from empire.plugins.ui.queries import QueryScope
from empire.plugins.ui.series_chart import SeriesChart


class ReviewPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future = self.requested = self.applied = self.data = None
        self.dirty = False
        layout = QVBoxLayout(self)
        title = QLabel('市场复盘')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(DataNote('收盘市场事实 · 连板演变 · 题材轮动',
            '远航HS/GEM2STAR口径，含来源实际返回的ST等证券。—表示未知或零分母，不代表0。'
            '不生成尚无公式的情绪评分、仓位建议或人工策略。'))
        today = datetime.now(CHINA).date()
        self.start = accessible(QLineEdit(str(today - timedelta(days=89))), '复盘开始日期')
        self.end = accessible(QLineEdit(str(today)), '复盘结束日期')
        self.selected = accessible(QComboBox(), '复盘交易日')
        self.selected.setMinimumContentsLength(12)
        self.selected.currentIndexChanged.connect(self.select_day)
        self.button = QPushButton('查询复盘')
        self.button.clicked.connect(self.apply_filters)
        layout.addWidget(QueryForm([('开始日期', self.start), ('结束日期', self.end),
                                   ('复盘交易日', self.selected)], [self.button]))
        self.status = QLabel('读取已归档日终数据；最多120自然日。点击查询后选择复盘交易日。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        cards = QGridLayout()
        self.cards = {}
        for index, (key, label) in enumerate(METRICS):
            card = QLabel(label + '\n—')
            card.setAccessibleName(label)
            card.setStyleSheet('QLabel { background:#edf4fb; color:#163651; border:1px solid #d4e1ef;'
                              'border-radius:6px; padding:9px; font-size:15px; }')
            self.cards[key] = card
            cards.addWidget(card, index // 4, index % 4)
        layout.addLayout(cards)
        self.tabs = QTabWidget()
        self.graph = chart()
        self.tabs.addTab(self.graph, '市场趋势')
        self.rates = SeriesChart([dict(title='封板与连板晋级（%）', gap=None, zero=True,
            fields=[(1, '封板率'), (2, '1进2率'), (3, '连板晋级率')])])
        self.tabs.addTab(self.rates, '晋级趋势')
        self.tables = build_tables(self.tabs)
        layout.addWidget(self.tabs, 1)
        self.coverage = QLabel('题材缺失日期保留空缺；连续涨停以交易日序列计算，历史缺口会中断计算。')
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)

    def apply_filters(self):
        self.applied = self.start.text().strip(), self.end.text().strip()
        self.dirty = True
        self.status.setText('正在读取所选日期范围…')

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.applied:
                self.scope.discard('review', future)
            else:
                try:
                    self.data = self.scope.result('review', future)
                    previous = self.selected.currentData()
                    with QSignalBlocker(self.selected):
                        self.selected.clear()
                        for row in reversed(self.data['days']):
                            self.selected.addItem(str(row['day']) + (' · 待采集' if row['up'] is None else ''),
                                                  row['day'])
                        index = self.selected.findData(previous)
                        if index < 0:
                            index = next((i for i, row in enumerate(reversed(self.data['days']))
                                          if row['up'] is not None), 0)
                        self.selected.setCurrentIndex(index)
                    self.select_day()
                    self.status.setText(f'查询范围 {self.requested[0]}～{self.requested[1]} · '
                                        f'读取时间 {self.data["queried_at"]}（北京时间）')
                except Exception as exc:
                    self.data = None
                    self.clear_result()
                    self.status.setText(redact(exc, self.shell.cfg))
        if self.isVisible() and self.dirty and self.future is None:
            self.dirty = False
            self.requested = self.applied
            self.future = self.scope.invoke('review', self.shell.runtime, 'market.review.query',
                                            'review', *self.requested)

    def clear_result(self):
        with QSignalBlocker(self.selected):
            self.selected.clear()
        for key, label in METRICS:
            self.cards[key].setText(label + '\n—')
        self.graph.set_series([], '没有可展示的查询结果')
        self.rates.set_series([], '没有可展示的查询结果')
        for widget in self.tables.values():
            widget.setRowCount(0)
        self.coverage.setText('没有可展示的查询结果；请检查日期及数据覆盖。')

    def select_day(self, *_):
        if not self.data or not self.data['days']:
            self.clear_result()
            return
        selected = self.selected.currentData()
        if selected is None:
            return
        current, count = render(self.tables, self.graph, self.data, selected)
        self.rates.set_series([(str(r['day']), r['sealed'], r['first_promotion'], r['promotion'])
                               for r in self.data['days'] if r['day'] <= selected])
        for key, label in METRICS:
            self.cards[key].setText(label + '\n' + value(current[key],
                key in ('sealed', 'first_promotion', 'promotion')))
        names = ' / '.join(r['name'] for r in current['leaders']) or '—'
        self.coverage.setText(f'{selected} · {current["note"]} · 并列最高：{names}。'
            f'近10交易日题材覆盖 {count}/10' + ('，热度合计可查。' if count == 10 else '，不足10日不计算热度合计。') +
            ' 题材轮动可横向滚动，点击题材高亮。最高板不是主观总龙头。')

    def apply_navigation_context(self, context):
        if context.start:
            self.start.setText(context.start)
        if context.end:
            self.end.setText(context.end)
        self.apply_filters()


class ReviewUi(UiPlugin):
    manifest = PluginManifest('ui.market_review', '市场复盘页面', provides=('ui.pages.market_review',))

    def create_pages(self):
        return (PageContribution('market_review', '市场复盘', ReviewPage, '市场复盘', 62,
            '涨停炸板、封板率、连板梯队、最高板演变、题材轮动与热度', top_level=True,
            category='市场复盘', source='远航 / 开盘啦', cache_policy='lru',
            database_tables=('trade_calendar', 'yuanhang_limit_pool', 'yuanhang_limit_member', 'theme_daily')),)
