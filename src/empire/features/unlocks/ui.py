"""Lazy list facts with explicitly shared shareholder detail groups."""
from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import accessible, bind_find, hint
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_cards import CardReader, card, fields
from empire.plugins.ui.queries import QueryScope


class UnlockPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.scope = shell, QueryScope(self)
        self.applied, self.after, self.next_cursor, self.history = ('', '', ''), None, None, []
        self.future = self.detail_future = None
        self.dirty, self.group = True, ''
        layout = QVBoxLayout(self)
        title = QLabel('大小非解禁个股与明细（通达信）')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(hint('解禁日期不是公告日期；并列列表记录保留，对应股东明细按请求组共享，不能重复相加。'))
        bar = QHBoxLayout()
        self.code, self.start, self.end = QLineEdit(), QLineEdit(), QLineEdit()
        for field, label, placeholder in ((self.code, '证券', '六位代码或统一证券代码'),
                (self.start, '开始日期', '开始 YYYY-MM-DD'), (self.end, '截止日期', '截止 YYYY-MM-DD')):
            accessible(field, '大小非解禁' + label)
            field.setPlaceholderText(placeholder)
            field.returnPressed.connect(self.find)
            bar.addWidget(field)
        bind_find(self, self.code)
        find, manage = QPushButton('查询 / 刷新'), QPushButton('管理采集任务')
        find.clicked.connect(self.find)
        manage.clicked.connect(lambda: shell.navigate('collection', NavigationContext(task_id='tdx-unlocks')))
        bar.addWidget(find)
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = hint('读取已归档数据…')
        layout.addWidget(self.status)
        self.reader, self.detail = CardReader('大小非解禁列表'), CardReader('共享股东明细')
        self.reader.anchorClicked.connect(self.open_detail)
        layout.addWidget(self.reader, 2)
        layout.addWidget(self.detail, 1)
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
        self.clear_results()

    def move(self, forward):
        if forward and self.next_cursor:
            self.history.append(self.after)
            self.after = self.next_cursor
        elif not forward and self.history:
            self.after = self.history.pop()
        self.dirty = True
        self.clear_results()

    def clear_detail(self):
        self.scope.cancel('detail')
        self.detail_future, self.group = None, ''
        self.detail.present('<p>从当前列表选择一项查看共享股东明细。</p>', identity=None)

    def clear_results(self):
        self.scope.cancel('records')
        self.future = None
        self.clear_detail()
        position = (self.reader.save_position() if self.reader.signature
                    and self.reader.signature[0] == self.spec() else 0)
        self.reader.present('<p>读取已归档数据…</p>', identity=self.spec())
        self.reader.restore_position(position)
        self.status.setText('读取已归档数据…')
        self.previous.setEnabled(False)
        self.next.setEnabled(False)

    def spec(self):
        return (*self.applied, self.after, 200)

    def open_detail(self, url):
        if url.scheme() != 'unlock':
            return
        self.group = url.path()
        self.detail.present('<p>读取共享股东明细…</p>', identity=self.group)
        self.detail_future = self.scope.invoke('detail', self.shell.runtime, 'unlocks.tdx_query', 'details', self.group)

    def tick(self):
        if not self.isVisible():
            return
        if self.detail_future and self.detail_future.done():
            future, self.detail_future = self.detail_future, None
            try:
                rows = self.scope.result('detail', future)
                html = ''.join(card(r['holder'], fields([('解禁原因', r['reason']), ('数量（股）', r['shares']),
                    ('相同事实出现序号', r['occurrence'])]), '共享请求组明细') for r in rows)
                self.detail.present(html or '<p>已归档请求组没有股东明细；查看列表中的来源空状态与数据准备。</p>', identity=self.group)
            except Exception as exc:
                self.detail.present('<p>' + escape(redact(exc, self.shell.runtime.config)) + '</p>', identity=self.group)
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
                html = ''
                for r in result['rows']:
                    text = fields([('解禁日期', r['unlock_date']), ('解禁原因', r['reason']),
                        ('数量（股）', r['shares']), ('来源总股本基数（股）', r['total_shares']),
                        ('行业', r['industry']), ('明细状态', r['detail_status']), ('共享明细条数', r['detail_count'])])
                    text += '<p><a href="unlock:' + r['group_key'] + '">查看对应共享股东明细</a></p>'
                    html += card(r['unified_code'] + ' ' + (r['name'] or ''), text, '大小非解禁列表事实')
                self.reader.present(html or '<p>当前条件无已归档记录；不代表来源没有数据。</p>', identity=self.spec())
                self.status.setText(f'本页{len(result["rows"])}条；完整性与实际覆盖见数据准备。')
            except Exception as exc:
                self.status.setText(redact(exc, self.shell.runtime.config))
        if self.dirty and self.future is None:
            self.dirty, self.requested = False, self.spec()
            self.future = self.scope.invoke('records', self.shell.runtime, 'unlocks.tdx_query', 'list_records', *self.requested)

    def hideEvent(self, event):
        self.timer.stop()
        self.scope.cancel_all()
        self.future = self.detail_future = None
        self.clear_detail()
        self.dirty = True
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(300)

    def save_ui_state(self):
        return dict(drafts=[f.text() for f in (self.code, self.start, self.end)], applied=self.applied,
                    after=self.after, history=self.history, position=self.reader.save_position())

    def restore_ui_state(self, state):
        for field, value in zip((self.code, self.start, self.end), state['drafts'], strict=True):
            field.setText(value)
        self.applied, self.after, self.history = tuple(state['applied']), state['after'], state['history']
        self.reader.restore_position(state.get('position', 0))
        self.dirty = True

    def apply_navigation_context(self, context):
        if context.unified_code:
            self.code.setText(context.unified_code)
            self.find()


class UnlockUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.tdx_unlocks', '大小非解禁界面', provides=('ui.pages.tdx_unlocks',))

    def create_pages(self):
        return (PageContribution('unlocks', '大小非解禁个股与明细', UnlockPage, '数据浏览', 50,
            '按证券、解禁日期查询列表事实及共享股东明细', database_tables=('restricted_share_unlock', 'restricted_share_unlock_detail'),
            catalogued=True, category='股东数据', source='通达信', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id='tdx-unlocks'))),)
