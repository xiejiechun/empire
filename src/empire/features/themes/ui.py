"""Lazy seven-calendar-day replay and latest-detail browsing."""
from datetime import datetime
from decimal import Decimal
from html import escape
from time import monotonic

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
from empire.features.themes.repository import TABLE_COLUMNS
from empire.plugins.ui.common import accessible, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope


def metric(value, *, percent=False):
    if value is None:
        return '来源未提供'
    return f'{Decimal(value):.2f}%' if percent else str(value)


class ThemePage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.future, self.dirty, self.after, self.next_cursor = None, True, '', None
        self.previous_cursors = []
        self.displayed_rows, self.last_refresh = [], monotonic()
        layout = QVBoxLayout(self)
        title = QLabel('开盘啦题材库')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('日内记录保留今天及之前6个自然日；详情只显示最新内容。电脑或Redis重启前的日内记录不能恢复。'))
        self.mode = QComboBox()
        self.mode.addItems(['当日最新采样', '七日日内回放', '长期每日列表', '最新题材详情'])
        self.day, self.at, self.theme = QLineEdit(datetime.now(CHINA).date().isoformat()), QLineEdit(), QLineEdit()
        self.day.setPlaceholderText('日期 YYYY-MM-DD')
        self.at.setPlaceholderText('北京时间 HH:MM:SS；留空为当日最后采样')
        self.theme.setPlaceholderText('详情填主题材ID，例如148（军工）；子题材填父ID')
        for control, label in ((self.mode, '查看方式'), (self.day, '题材日期'), (self.at, '回放时刻'), (self.theme, '主题材ID')):
            accessible(control, label)
        bar = QHBoxLayout()
        bar.addWidget(self.mode)
        bar.addWidget(self.day)
        bar.addWidget(self.at)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        bar.addWidget(self.theme)
        refresh, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集任务')
        refresh.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id='kaipanla-themes')))
        bar.addWidget(refresh)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status, self.reader = hint('正在读取题材…'), CardReader('题材列表与详情')
        self.reader.selected.connect(self.choose_detail)
        layout.addWidget(self.status)
        layout.addWidget(self.reader)
        bar = QHBoxLayout()
        self.back, self.forward = QPushButton('上一页'), QPushButton('下一页')
        self.back.clicked.connect(lambda: self.move(False))
        self.forward.clicked.connect(lambda: self.move(True))
        bar.addWidget(self.back)
        bar.addWidget(self.forward)
        bar.addStretch()
        layout.addLayout(bar)
        self.applied = self.drafts()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def drafts(self):
        return (self.mode.currentIndex(), self.day.text().strip(), self.at.text().strip(), self.theme.text().strip())

    def find(self):
        self.applied, self.after, self.previous_cursors = self.drafts(), '', []
        self.dirty = True

    def choose_detail(self, index):
        if not 0 <= index < len(self.displayed_rows):
            return
        self.theme.setText(self.displayed_rows[index]['source_theme_id'])
        self.mode.setCurrentIndex(3)
        self.find()

    def move(self, forward):
        if forward and self.next_cursor:
            self.previous_cursors.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.previous_cursors:
            self.after = self.previous_cursors.pop()
        self.dirty = True

    def spec(self):
        return (*self.applied, self.after)

    def request(self):
        mode, day, at, theme = self.applied
        if mode == 0:
            return 'current', ()
        if mode == 1:
            instant = datetime.fromisoformat(day + 'T' + at).replace(tzinfo=CHINA).isoformat() if at else ''
            return 'intraday', (day, instant)
        if mode == 2:
            return 'daily', (day, self.after)
        return 'detail_page', (theme, self.after)

    def present(self, result):
        self.next_cursor = result.get('next') if result else None
        if not result:
            self.reader.present('<p>这个时间或题材尚无成功采集记录，不能据此判断来源为空。</p>', identity=self.spec())
            self.status.setText('暂无记录；检查采集任务和所选日期。')
        elif self.applied[0] == 3:
            head = result['head']
            html = card(head['name'], fields([('简介', head['brief']), ('正文', head['introduction']),
                ('归档内容观测时间', str(head['observed_at']))]), '最新详情；不是历史时点正文')
            html += ''.join(card(r['stock_name'] + ' · ' + r['unified_code'], fields([
                ('分类', r['category_name'] or '未分类'), ('题材理由', r['reason'] or '来源未提供'),
                ('相同来源关联次数', r['occurrences'])]), '') for r in result['rows'])
            self.reader.present(html, identity=self.spec())
            self.status.setText(f'本页{len(result["rows"])}条企业关联；不同理由分别保留。')
        else:
            rows = result['rows']
            if self.applied[0] < 2:
                rows = sorted(rows, key=lambda r: r['display_order'])
            self.displayed_rows = rows
            html = ''.join(card(r['name'] + ' · ' + r['theme_id'], fields([
                ('排名', metric(r['rank_no'])), ('热度', metric(r['hot_score'])),
                ('涨跌幅', metric(r['change_rate'], percent=True)), ('涨停数量', r['limit_up_count']),
                ('父题材', r['parent_id'] or '主题材'), ('详情主题材ID', r['source_theme_id'])])
                + f'<p><a href="record:{index}">查看最新详情</a></p>', '') for index, r in enumerate(rows))
            self.reader.present(html or '<p>当前页无数据。</p>', identity=self.spec())
            self.status.setText(f'{len(rows)}条；采样时间：{result.get("at", "见所选每日版本")}；'
                                '未采样时段没有可回放记录。')
        self.back.setEnabled(bool(self.previous_cursors))
        self.forward.setEnabled(bool(self.next_cursor))

    def tick(self):
        if not self.isVisible():
            return
        if self.applied[0] == 0 and self.drafts() == self.applied and monotonic() - self.last_refresh >= 30:
            self.last_refresh, self.dirty = monotonic(), True
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.spec():
                self.scope.discard('theme', future)
                self.dirty = True
                return
            try:
                self.present(self.scope.result('theme', future))
            except Exception as exc:
                self.status.setText(escape(redact(exc, self.shell.runtime.config)))
        if self.dirty and self.future is None:
            self.dirty, self.requested = False, self.spec()
            try:
                method, args = self.request()
                self.future = self.scope.invoke('theme', self.shell.runtime, 'themes.query', method, *args)
            except Exception as exc:
                self.status.setText(escape(redact(exc, self.shell.runtime.config)))

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future, self.dirty = None, True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(drafts=self.drafts(), applied=self.applied, after=self.after,
                    history=self.previous_cursors, position=self.reader.save_position())

    def restore_ui_state(self, state):
        mode, day, at, theme = state['drafts']
        self.mode.setCurrentIndex(mode)
        for field, value in zip((self.day, self.at, self.theme), (day, at, theme), strict=True):
            field.setText(value)
        self.applied, self.after, self.previous_cursors = tuple(state['applied']), state['after'], state['history']
        self.reader.restore_position(state.get('position', 0))
        self.dirty = True


class ThemeUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.themes', '题材浏览界面', provides=('ui.pages.themes',))

    def create_pages(self):
        return (PageContribution('themes', '开盘啦题材库', ThemePage, '数据浏览', 80,
            '热度、排名、涨跌幅、涨停数量及七日日内变化', catalogued=True,
            category='题材数据', source='开盘啦', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS),
            management=NavigationTarget('collection', NavigationContext(task_id='kaipanla-themes'))),)
