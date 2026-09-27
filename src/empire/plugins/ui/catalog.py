"""Searchable data catalogue generated from page contributions, not collector menus."""
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.plugins.ui.common import (
    Pager,
    accessible,
    bind_find,
    restore_table_identity,
    table_identity_state,
    update_options,
)


class DataCatalogPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        from empire.plugins.ui.common import hint, table

        self.shell, self.offset, self.entries = shell, 0, []
        layout = QVBoxLayout(self)
        title = QLabel("数据目录")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(hint("按业务分类或来源查找数据，打开后查看对应的数据列表。"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索数据名称、来源或用途")
        self.search.setClearButtonEnabled(True)
        self.category, self.source = QComboBox(), QComboBox()
        accessible(self.search, "搜索数据目录", "输入数据名称、来源或用途；按 Ctrl+F 可回到此处。")
        accessible(self.category, "按业务分类筛选")
        accessible(self.source, "按数据来源筛选")
        bind_find(self, self.search)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        filters.addWidget(self.source)
        layout.addLayout(filters)
        self.table = table(["数据名称", "业务分类", "来源", "用途"])
        self.table.setAccessibleName("数据目录结果")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 220)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.pager = Pager()
        self.pager.changed.connect(self.change_page)
        layout.addWidget(self.pager)
        self.open_button = QPushButton("打开数据")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_selected)
        actions = QHBoxLayout()
        actions.addWidget(hint("选择一项后打开，也可双击数据名称。"))
        actions.addStretch()
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        self.table.itemDoubleClicked.connect(lambda _: self.open_selected())
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(self.table.currentRow() >= 0))
        self.search.textChanged.connect(self.filter_changed)
        self.category.currentIndexChanged.connect(self.filter_changed)
        self.source.currentIndexChanged.connect(self.filter_changed)
        self.render()

    def showEvent(self, event):
        super().showEvent(event)
        self.render()

    def save_ui_state(self):
        return {"search": self.search.text(), "category": self.category.currentData(),
                "source": self.source.currentData(), "offset": self.offset,
                "table": table_identity_state(self.table)}

    def restore_ui_state(self, state):
        self.search.blockSignals(True)
        self.search.setText(state["search"])
        self.search.blockSignals(False)
        self.category.setCurrentIndex(max(0, self.category.findData(state["category"])))
        self.source.setCurrentIndex(max(0, self.source.findData(state["source"])))
        self.offset = state["offset"]
        restore_table_identity(self.table, state["table"])
        self.render()

    def filter_changed(self):
        self.offset = 0
        self.render()

    def change_page(self, offset):
        self.offset = offset
        self.render()

    def render(self):
        from empire.plugins.ui.common import rows

        pages = [p for p in self.shell.runtime.page_contributions() if p.catalogued]
        update_options(self.category, [p.category for p in pages], "全部分类")
        update_options(self.source, [p.source for p in pages], "全部来源")
        query = self.search.text().strip().casefold()
        matches = [p for p in pages if (not self.category.currentData() or p.category == self.category.currentData())
                   and (not self.source.currentData() or p.source == self.source.currentData())
                   and query in f"{p.title} {p.source} {p.description}".casefold()]
        matches.sort(key=lambda p: (p.category, p.order, p.id))
        self.offset = min(self.offset, max(0, (len(matches) - 1) // self.pager.limit * self.pager.limit))
        self.entries = matches[self.offset:self.offset + self.pager.limit]
        rows(self.table, [[p.title, p.category, p.source, p.description] for p in self.entries],
             keys=[p.id for p in self.entries])
        if self.entries and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.open_button.setEnabled(bool(self.entries))
        self.pager.update_result(len(matches), self.offset)

    def open_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries):
            self.shell.navigate(self.entries[row].id)
