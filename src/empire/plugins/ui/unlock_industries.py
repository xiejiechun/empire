"""Lazy industry month summary reader."""
from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import accessible, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope


class UnlockIndustryPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.applied, self.after, self.history, self.next_cursor = ('', '', ''), None, [], None
        self.future, self.dirty = None, True
        layout = QVBoxLayout(self)
        title = QLabel('大小非解禁行业（通达信）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('市值与比例使用来源估值基准日；退出来源目录的月份仅保留历史参考。'))
        bar = QHBoxLayout()
        self.industry, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label, placeholder in ((self.industry, '行业', '来源行业名称（精确匹配）'),
                (self.start, '开始月份', '开始 YYYY-MM-01'), (self.end, '截止月份', '截止 YYYY-MM-01')):
            accessible(field, '解禁行业' + label)
            field.setPlaceholderText(placeholder)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        find, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集任务')
        find.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id='tdx-unlock-industries')))
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status, self.reader = hint('读取已归档数据…'), CardReader('解禁行业汇总')
        layout.addWidget(self.status)
        layout.addWidget(self.reader)
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
        self.applied = tuple(f.text().strip() for f in (self.industry, self.start, self.end))
        self.after, self.history, self.dirty = None, [], True

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True

    def spec(self):
        return (*self.applied, self.after)

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
                html = ''.join(card(r['industry'] + ' · ' + r['unlock_month'][:7], fields([
                    ('估值基准日', r['basis_date']), ('解禁数量（股）', r['shares']), ('解禁市值（元）', r['unlock_value']),
                    ('行业总市值（元）', r['market_cap']), ('行业流通市值（元）', r['negotiable_cap']),
                    ('占总市值（%）', r['market_percent']), ('占流通市值（%）', r['float_percent'])]), '来源行业月汇总')
                    for r in result['rows'])
                self.reader.present(html or '<p>当前条件没有已归档行业汇总。</p>', identity=self.spec())
                self.status.setText(f'本页{len(result["rows"])}条；完整性与来源窗口见数据准备。')
            except Exception as exc:
                self.status.setText(escape(redact(exc, self.shell.runtime.config)))
        if self.dirty and self.future is None:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('records', self.shell.runtime, 'unlock_industries.tdx_query', 'list_records', *self.requested)

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future, self.dirty = None, True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(drafts=[f.text() for f in (self.industry, self.start, self.end)], applied=self.applied,
                    after=self.after, history=self.history, position=self.reader.save_position())

    def restore_ui_state(self, state):
        for field, value in zip((self.industry, self.start, self.end), state['drafts'], strict=True):
            field.setText(value)
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], state['history']
        self.reader.restore_position(state.get('position', 0))
        self.dirty = True


class UnlockIndustryUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.tdx_unlock_industries', '大小非解禁行业界面', provides=('ui.pages.tdx_unlock_industries',))

    def create_pages(self):
        return (PageContribution('unlock_industries', '大小非解禁行业', UnlockIndustryPage, '数据浏览', 51,
            '按解禁月份、行业查看数量、市值及比例', database_tables=('restricted_share_unlock_industry',),
            catalogued=True, category='股东数据', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id='tdx-unlock-industries'))),)
