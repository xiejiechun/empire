"""Selected-security summary and explicit data-page links; no per-row database reads."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from empire.plugins.ui.preview_navigation import navigate_security, security_context


class StockPreview:
    def install_preview(self, layout):
        self.security_summary = QLabel('选择一只股票，查看资料、行情、报表或事件。')
        self.security_summary.setWordWrap(True)
        layout.addWidget(self.security_summary)
        links = QHBoxLayout()
        self.preview_links = []
        for title, page in (('公司资料', 'listings'), ('日K线', 'adjustment'), ('利润表', 'income'),
                            ('分红送转', 'dividends'), ('更名事件', 'names_security')):
            button = QPushButton(title)
            button.setEnabled(False)
            button.clicked.connect(lambda _, target=page: self.open_preview(target))
            self.preview_links.append(button)
            links.addWidget(button)
        layout.addLayout(links)
        links = QHBoxLayout()
        for title, page in (('资产负债表', 'balance'), ('现金流量表', 'cashflow'),
                            ('停复牌', 'suspensions'), ('所属行业', 'industries'), ('所属指数', 'indices')):
            button = QPushButton(title)
            button.setEnabled(False)
            button.clicked.connect(lambda _, target=page: self.open_preview(target))
            self.preview_links.append(button)
            links.addWidget(button)
        more = QPushButton('显示技术身份列')
        more.setCheckable(True)
        more.toggled.connect(lambda enabled: [self.table.setColumnHidden(c, not enabled) for c in (2, 4)])
        links.addWidget(more)
        self.table.hideColumn(2)
        self.table.hideColumn(4)
        layout.addLayout(links)
        self.table.itemSelectionChanged.connect(self.select_preview)
        self.table.itemDoubleClicked.connect(lambda _: self.open_preview('listings'))

    def select_preview(self):
        index = self.table.currentRow()
        for button in self.preview_links:
            button.setEnabled(index >= 0)
        if index >= 0:
            self.security_summary.setText(self.table.item(index, 1).text() + ' · '
                + self.table.item(index, 2).text() + ' · 进入数据页后显示该项目已归档范围，阅读不启动采集。')
        else:
            self.security_summary.setText('选择一只股票，查看资料、行情、报表或事件。')

    def open_preview(self, target):
        index = self.table.currentRow()
        if index >= 0:
            navigate_security(self.shell, target, self.table.item(index, 2).text())

    def apply_navigation_context(self, context):
        code, market = security_context(context)
        self.search.setText(code)
        self.market.setCurrentIndex(self.market.findData(market))
        self.search_changed()
