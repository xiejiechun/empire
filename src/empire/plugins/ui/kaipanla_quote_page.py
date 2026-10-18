"""Quote-page query ownership; related trend is optional and never collects."""
from PySide6.QtWidgets import QPushButton

from empire.contracts.ui import NavigationContext
from empire.core.redaction import redact
from empire.plugins.collectors.kaipanla_kinds import capability
from empire.plugins.ui.kaipanla_products import ProductPage
from empire.plugins.ui.kaipanla_quote_view import QuoteView


class QuotePage(ProductPage):
    def build_body(self, layout):
        self.view = QuoteView()
        self.related, self.related_identity = None, None
        layout.addWidget(self.view)
        self.trend_link = QPushButton('查看该证券日独立分时走势')
        self.trend_link.clicked.connect(self.open_trend)
        layout.addWidget(self.trend_link)

    def open_trend(self):
        if self.loaded_scope:
            market, code, day = self.loaded_scope
            self.shell.navigate('kaipanla_trend', NavigationContext(unified_code=code+'.'+market, day=day))

    def render(self):
        self.scope.cancel('quote-trend')
        self.related = None
        self.view.set_quote(self.payload, self.requested)
        if self.payload:
            self.status.setText('已读取该日历史盘口快照；关联走势单独读取已归档分时，缺失不影响盘口展示。')
            self.related_identity = self.requested
            self.related = self.scope.invoke('quote-trend', self.shell.runtime, capability('trend'), 'day', *self.requested)

    def tick(self):
        super().tick()
        if self.scope.closed:
            return
        if not self.related or not self.related.done():
            return
        future, self.related = self.related, None
        if self.related_identity != self.applied:
            self.scope.discard('quote-trend', future)
            return
        try:
            result = self.scope.result('quote-trend', future)
            points = result['data']['data']['trend'] if result else []
            self.view.chart.set_series(points, self.view.reference, '该证券日尚无已归档分时走势')
        except Exception as exc:
            self.view.chart.set_series([], self.view.reference, '分时走势不可用；盘口快照仍可浏览')
            self.view.chart.setToolTip(redact(exc, self.shell.cfg))

    def save_ui_state(self):
        return {**super().save_ui_state(), 'depth': self.view.depth.currentIndex()}

    def restore_ui_state(self, state):
        super().restore_ui_state(state)
        self.view.depth.setCurrentIndex(state.get('depth', 0))
