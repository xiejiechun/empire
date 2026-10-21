"""On-demand read-only distribution analysis within the existing dividend page."""
from PySide6.QtWidgets import QPushButton, QTextBrowser, QVBoxLayout, QWidget

from empire.core.redaction import redact
from empire.features.capital_actions.distribution_text import distribution_text


class DistributionPanel(QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.future, self.requested = page, None, None
        layout = QVBoxLayout(self)
        self.button = QPushButton('计算名义派息（使用上方证券及日期）')
        self.button.clicked.connect(self.calculate)
        layout.addWidget(self.button)
        self.result = QTextBrowser()
        self.result.setAccessibleName('名义派息逐笔与汇总')
        layout.addWidget(self.result)
        self.invalidate()
        for field in (page.code, page.start, page.end):
            field.textChanged.connect(self.invalidate)
        page.market.currentIndexChanged.connect(self.invalidate)

    def values(self):
        p = self.page
        return (p.code.text().strip(), p.market.currentData(), p.start.text().strip(), p.end.text().strip())

    def invalidate(self):
        self.page.query_scope.cancel('distribution')
        self.future = None
        self.button.setEnabled(True)
        self.result.setPlainText('未检查。指定六位证券和起止日期后计算；不按方案列表分页或状态筛选求和。\n'
                                 '名义每股含税派息，不是到账现金；不需要股价或回购数据。')

    def calculate(self):
        self.invalidate()
        self.requested = self.values()
        code, _, start, end = self.requested
        if len(code) != 6 or not code.isascii() or not code.isdigit() or not start or not end:
            self.result.setPlainText('数据阻断：须指定六位证券及起止日期。')
            return
        self.future = self.page.query_scope.invoke('distribution', self.page.shell.runtime,
            'dividends.query', 'distribution_summary', dict(codes=[code], start=start, end=end))
        self.button.setEnabled(False)
        self.result.setPlainText('正在只读核验完整证券单元及实施事件……')

    def tick(self):
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            self.button.setEnabled(True)
            if self.requested != self.values():
                self.page.query_scope.discard('distribution', future)
                self.invalidate()
                return
            try:
                result = self.page.query_scope.result('distribution', future)
                market = self.requested[1]
                if market and any(r['security'][-2:] != market for r in result['securities']):
                    raise ValueError('所选市场与已证明证券不一致，请选择正确市场或全部市场自动识别')
                self.result.setPlainText(distribution_text(result))
            except Exception as exc:
                self.result.setPlainText('数据阻断：' + redact(exc, self.page.shell.cfg))
