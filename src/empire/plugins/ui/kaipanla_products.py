"""Lazy independent product pages, displaying bounded slices of archived arrays."""
from functools import partial

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.core.redaction import redact
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, capability, project
from empire.plugins.ui.common import accessible, rows
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope

HEADERS = {
    'trend': ['分钟', '价格', '均价', '来源量', '来源标记'],
    'auction': ['分钟', '价格', '来源标记', '来源量'],
    'volume': ['分钟', '成交量（来源单位）', '成交额（来源单位）', '来源标记'],
    'trades': ['时间', '价格', '来源标记 1', '来源量', '来源字段 4', '来源字段 5', '来源字段 6', '来源字段 7'],
    'entrust': ['分钟', '买委托量', '卖委托量', '买委托额', '卖委托额'],
    'large_order': ['分钟', '大单净额'],
}


class ProductPage(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind, self.scope = shell, kind, QueryScope(self)
        self.future, self.applied, self.requested, self.dirty = None, None, None, False
        self.points, self.offset, self.payload = [], 0, None
        item = PRODUCTS[kind]
        layout = QVBoxLayout(self)
        title = QLabel('开盘啦' + item.title)
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel(item.note + '。查询只读取已归档数据；本项自动采集默认关闭。')
        note.setWordWrap(True)
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.market, self.code = QComboBox(), QLineEdit('000001')
        self.market.addItems(['SZ', 'SH', 'BJ'])
        self.code.setMaxLength(6)
        self.day = QDateEdit(QDate.currentDate().addDays(-1))
        self.day.setDisplayFormat('yyyy-MM-dd')
        self.day.setCalendarPopup(True)
        self.day.setMinimumDate(QDate(2021, 1, 1))
        for widget, name in ((self.market, '市场'), (self.code, '证券代码'), (self.day, '交易日')):
            accessible(widget, item.title + name)
            bar.addWidget(widget)
        find = QPushButton('查询')
        find.clicked.connect(self.find)
        self.code.returnPressed.connect(self.find)
        bar.addWidget(find)
        manage = QPushButton('前往采集任务')
        manage.clicked.connect(lambda: shell.navigate_management(item.requirement))
        bar.addWidget(manage)
        layout.addLayout(bar)
        self.status = QLabel('选择证券日查询；没有数据不能推断为无成交或停牌。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.build_body(layout)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def build_body(self, layout):
        item = PRODUCTS[self.kind]
        self.table = QTableWidget(0, 2)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        accessible(self.table, item.title + '数据')
        layout.addWidget(self.table, 1)
        paging = QHBoxLayout()
        for label, step in (('上一页', -200), ('下一页', 200)):
            button = QPushButton(label)
            button.clicked.connect(partial(self.move, step))
            paging.addWidget(button)
        self.position = QLabel('每页最多 200 条')
        paging.addWidget(self.position)
        layout.addLayout(paging)

    def find(self):
        self.applied = (self.market.currentText(), self.code.text().strip(), self.day.date().toString('yyyy-MM-dd'))
        self.dirty = True

    def move(self, step):
        self.offset = max(0, min(max(0, ((len(self.points) - 1) // 200) * 200), self.offset + step))
        self.render()

    def render(self):
        item = PRODUCTS[self.kind]
        width = item.width + 1 if item.field else 2
        self.table.setColumnCount(width)
        headers = ['来源序号', *HEADERS[self.kind]] if item.field else ['字段', '内容']
        self.table.setHorizontalHeaderLabels(headers)
        values = self.points[self.offset:self.offset + 200]
        rows(self.table, [[self.offset + i + 1, *r] for i, r in enumerate(values)] if item.field else values)
        self.position.setText(f'{self.offset + 1 if self.points else 0}～{min(self.offset + 200, len(self.points))} / {len(self.points)}')

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.scope.close()
            self.timer.stop()
            return
        if self.future and self.future.done():
            future, self.future = self.future, None
            if self.requested != self.applied:
                self.scope.discard('day', future)
            else:
                try:
                    result = self.scope.result('day', future)
                    self.points, self.offset, self.payload = [], 0, result['data'] if result else None
                    if result is None:
                        self.status.setText('本项证券日没有已归档数据；请核对采集状态。')
                    else:
                        data = result['data']['data']
                        field = PRODUCTS[self.kind].field
                        self.points = data[field] if field else []
                        self.status.setText('已读取本项完整证券日；按来源顺序分页展示，未合并同分钟或同秒记录。')
                    self.render()
                except Exception as exc:
                    self.status.setText(self.scope.failure_message('day', '查询失败', redact(exc, self.shell.cfg),
                                                                  stale=bool(self.points or self.payload)))
        if self.isVisible() and self.dirty and not self.future:
            self.dirty, self.requested = False, self.applied
            self.future = self.scope.invoke('day', self.shell.runtime, capability(self.kind), 'day', *self.requested)

    def save_ui_state(self):
        return dict(market=self.market.currentText(), code=self.code.text(), day=self.day.date().toString('yyyy-MM-dd'),
                    applied=self.applied)

    def restore_ui_state(self, state):
        self.market.setCurrentText(state['market'])
        self.code.setText(state['code'])
        self.day.setDate(QDate.fromString(state['day'], 'yyyy-MM-dd'))
        self.applied, self.dirty = state.get('applied'), bool(state.get('applied'))


def create_product_page(shell, kind):
    if kind == 'quote':
        from empire.plugins.ui.kaipanla_quote_page import QuotePage
        return QuotePage(shell, kind)
    return ProductPage(shell, kind)


class KaipanlaProductUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.kaipanla_' + kind, PRODUCTS[kind].title + '界面',
                                      provides=('ui.pages.kaipanla_' + kind,))

    def create_pages(self):
        item = PRODUCTS[self.kind]
        return (PageContribution('kaipanla_' + self.kind, '开盘啦' + item.title,
            partial(create_product_page, kind=self.kind), '数据浏览', 11, item.note,
            database_tables=('stock_market_day',), catalogued=True, category='高频行情', source='开盘啦',
            cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
