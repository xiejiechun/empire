"""SQL inventory presentation; no SQL or completeness decisions live in the page."""
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from empire.plugins.ui.common import accessible, hint, rows, table


class PreparationInventory(QWidget):
    def __init__(self):
        super().__init__()
        self.report = None
        layout = QVBoxLayout(self)
        self.summary = hint('打开页面读取估算库存；点击“精确盘点 MySQL”取得实际行数与日期边界。')
        layout.addWidget(self.summary)
        self.search = accessible(QLineEdit(), '搜索MySQL库存表')
        self.search.setPlaceholderText('搜索表名；库存始终为当前连接数据库全表范围')
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.table = table(['MySQL 表', '归属', '实际行数', '证券 / 指数数', '日期边界', '盘点状态'])
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(4, 250)
        layout.addWidget(self.table, 1)

    def render(self, report):
        self.report = report
        success = sum(r['count'] is not None for r in report['rows'])
        self.summary.setText(f"全库 {report['total']} 表；已处理 {report['checked']} 表，取得实际行数 {success} 表。"
                             f"读取 {report['started_at'][:19]} ～ {report['finished_at'][:19] or '进行中'}。"
                             + report['note'] + (' ' + report['error'] if report['error'] else ''))
        self.filter_rows()

    def filter_rows(self):
        if not self.report:
            return
        entries = [r for r in self.report['rows'] if self.search.text().strip().lower() in r['table'].lower()]
        rows(self.table, [[r['table'], r['category'],
                          f"{r['count']:,}" if r['count'] is not None else f"未查（估算 {r['estimated_rows']:,}）",
                          str(r['securities']) if r['securities'] is not None else '—',
                          f"{r['first']} ～ {r['last']} ({r['date_column']})" if r['first'] else '未核验 / 不适用',
                          r['status']] for r in entries], keys=[r['table'] for r in entries])
