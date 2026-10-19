"""Research readiness, explicit SQL inventory, scoped gaps and capability planning."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, PageContribution
from empire.features.preparation.ui_actions import PreparationActions
from empire.features.preparation.ui_detail import PreparationDetail
from empire.features.preparation.ui_directory import PreparationDirectoryBar, matches_view
from empire.features.preparation.ui_inventory import PreparationInventory
from empire.features.preparation.ui_scope import PreparationScopeBar
from empire.features.preparation.ui_words import (
    PRIORITY,
    STATUS,
    action,
    check_title,
    finding,
    plain,
)
from empire.plugins.ui.common import accessible, bind_find, hint, rows, table, update_options
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preview_layout import QueryForm
from empire.plugins.ui.queries import QueryScope


class PreparationPage(PreparationActions, QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.query_scope = QueryScope(self)
        self.future = None
        self.snapshot_future = None
        self.last_snapshot = 0
        self.active_request = None
        self.entries = []
        self.visible_entries = []
        self.report = None
        self.preferred = None
        self.needs_check = True
        self.operation = 'overview'
        self.scan_all = False
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel('数据准备')
        title.setObjectName('pageTitle')
        heading.addWidget(title)
        heading.addStretch()
        self.refresh_button = QPushButton('检查本次用途')
        self.refresh_button.clicked.connect(lambda: self.reload(False))
        heading.addWidget(self.refresh_button)
        self.copy_button = QPushButton('复制检查记录')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_report)
        heading.addWidget(self.copy_button)
        self.export_button = QPushButton('导出报告')
        self.export_button.clicked.connect(self.export_report)
        heading.addWidget(self.export_button)
        self.manage = QPushButton('打开采集任务')
        self.manage.clicked.connect(self.open_task)
        self.manage.setEnabled(False)
        heading.addWidget(self.manage)
        layout.addLayout(heading)
        layout.addWidget(hint('先选研究用途，再检查所需输入。完成范围、内容质量、用途限制分别判断；原料齐全不代表因子或策略已计算完成。'))
        actions = QHBoxLayout()
        self.inventory_button = QPushButton('精确盘点 MySQL')
        self.inventory_button.clicked.connect(self.scan_inventory)
        self.full_button = QPushButton('详细扫描全部项目')
        self.full_button.clicked.connect(lambda: self.reload(True))
        self.cancel_button = QPushButton('取消检查')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.browse_button = QPushButton('查看选中数据')
        self.browse_button.clicked.connect(self.open_data)
        self.browse_button.setEnabled(False)
        for button in (self.inventory_button, self.full_button, self.cancel_button, self.browse_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.scope_toggle = QPushButton('展开证券与日期范围（空=当前全池 / 来源完整范围）')
        self.scope_toggle.setCheckable(True)
        layout.addWidget(self.scope_toggle)
        self.scope_bar = PreparationScopeBar()
        self.scope_bar.changed.connect(self.mark_draft)
        self.scope_toggle.toggled.connect(self.scope_bar.details.setVisible)
        layout.addWidget(self.scope_bar)
        self.scope_bar.details.setVisible(False)
        self.summary = hint('正在读取库存概览；详细检查需手动开始。')
        layout.addWidget(self.summary)
        self.research_summary = hint('选择因子研究、策略回测或长期价值研究。')
        layout.addWidget(self.research_summary)
        self.test_summary = hint('开发测试记录与实际数据完成情况分别呈现。')
        layout.addWidget(self.test_summary)
        self.tabs = QTabWidget()
        research_page = QWidget()
        research_layout = QVBoxLayout(research_page)
        research_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(research_page, '研究就绪 / 缺口')
        self.inventory_view = PreparationInventory()
        self.tabs.addTab(self.inventory_view, 'MySQL 已有数据')
        self.research_conditions = QTextBrowser()
        self.research_conditions.setAccessibleName('研究条件和未完成计算')
        self.tabs.addTab(self.research_conditions, '研究条件')
        layout.addWidget(self.tabs, 1)
        self.directory = PreparationDirectoryBar()
        self.directory.view.currentIndexChanged.connect(self.filter_rows)
        research_layout.addWidget(self.directory)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索数据名称、内容或用途（Ctrl+F）')
        self.search.setClearButtonEnabled(True)
        accessible(self.search, '搜索需要准备的数据')
        bind_find(self, self.search)
        self.kind = QComboBox()
        self.category, self.priority, self.state = QComboBox(), QComboBox(), QComboBox()
        for combo, name in ((self.kind, '工作类型'), (self.category, '数据分类'), (self.priority, '准备顺序'), (self.state, '准备情况')):
            accessible(combo, name)
            combo.currentIndexChanged.connect(self.filter_rows)
        research_layout.addWidget(self.search)
        self.search.textChanged.connect(self.filter_rows)
        research_layout.addWidget(QueryForm([('工作类型', self.kind), ('数据分类', self.category),
                                    ('准备顺序', self.priority), ('准备情况', self.state)]))
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = table(['数据名称', '本次角色 / 类型', '来源', '来源集合', '内容质量', '用途可用性'])
        self.table.setAccessibleName('数据准备工作进展')
        for index, width in enumerate((240, 150, 190, 110, 140)):
            self.table.setColumnWidth(index, width)
        self.table.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(self.table)
        self.detail = PreparationDetail()
        splitter.addWidget(self.detail)
        for grid in (self.table, self.inventory_view.table, self.detail.table, self.detail.findings):
            grid.verticalHeader().setDefaultSectionSize(30)
            grid.setStyleSheet('QTableWidget::item { padding: 3px 6px; }')
        splitter.setSizes([360, 320])
        self.splitter = splitter
        research_layout.addWidget(splitter, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def page_activated(self):
        self.tick()

    def save_ui_state(self):
        index = self.table.currentRow()
        return dict(search=self.search.text(), kind=self.kind.currentData(), category=self.category.currentData(),
                    priority=self.priority.currentData(), state=self.state.currentData(),
                    scope=self.scope_bar.save(), view=self.directory.view.currentData(),
                    scope_open=self.scope_toggle.isChecked(), sizes=self.splitter.sizes(),
                    selected=self.visible_entries[index]['id'] if 0 <= index < len(self.visible_entries) else None)

    def restore_ui_state(self, state):
        self.search.setText(state['search'])
        self.preferred = state
        if 'scope' in state:
            self.scope_bar.restore(state['scope'])
        self.directory.view.setCurrentIndex(max(0, self.directory.view.findData(state.get('view', ''))))
        self.scope_toggle.setChecked(state.get('scope_open', False))
        if state.get('sizes'):
            self.splitter.setSizes(state['sizes'])

    def show_detail(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_entries):
            entry = self.visible_entries[index]
            self.detail.render(entry)
            self.manage.setText('打开计算页面' if entry.get('page') else '打开采集任务')
            self.manage.setEnabled(bool(entry.get('page') or entry['project']))
            self.browse_button.setEnabled(bool(self.data_page(entry)))
        else:
            self.detail.clear()
            self.manage.setEnabled(False)
            self.browse_button.setEnabled(False)

    def data_page(self, entry):
        if entry.get('page'):
            return entry['page']
        runtime = getattr(self.shell, 'runtime', None)
        pages = getattr(runtime, 'page_contributions', lambda: ())()
        matches = [p.id for p in pages if p.catalogued and p.management
                   and p.management.context.task_id == entry['project']]
        if entry['id'] in matches:
            return entry['id']
        return matches[0] if len(matches) == 1 else ''

    def open_data(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_entries):
            page = self.data_page(self.visible_entries[index])
            if page:
                self.shell.navigate(page)

    def open_task(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_entries):
            entry = self.visible_entries[index]
            if entry.get('page'):
                self.shell.navigate(entry['page'])
                return
            project = entry['project']
            if project:
                self.shell.navigate('collection', NavigationContext(task_id=project))

    def render(self, report):
        self.report = report
        self.entries = report['rows']
        for combo, field, label in ((self.kind, 'kind', '全部工作'), (self.category, 'category', '全部分类'),
                                    (self.priority, 'priority', '全部顺序'), (self.state, 'status', '全部状态')):
            values = list(STATUS) if field == 'status' else [r[field] for r in self.entries]
            update_options(combo, values, label)
            labels = PRIORITY if field == 'priority' else STATUS if field == 'status' else {}
            for index in range(1, combo.count()):
                combo.setItemText(index, labels.get(combo.itemData(index), combo.itemText(index)))
            if self.preferred:
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(self.preferred[field if field != 'status' else 'state'])))
                combo.blockSignals(False)
        research = report['research']
        counts = research['counts']
        self.summary.setText(
            f"{research['title']} · {research['focus']}：必需 {research['required']} 项；通过 {counts['ready']}，"
            f"有限制 {counts['limited']}，阻断 {counts['blocked']}，未核验 {counts['unknown']}，待建设 {counts['planned']}。"
            f"检查时间：{report['checked_at'][:19].replace('T', ' ') or '尚未检查'}。")
        self.summary.setToolTip(report['scope'])
        guards = research['guards']
        self.research_summary.setText('研究条件：' + '；'.join(f"{g['title']}：{g['state']}" for g in guards)
                                     if guards else '按来源声明范围逐项盘点，不计算全库完成百分比。')
        self.research_summary.setToolTip('\n\n'.join(g['title'] + '：' + g['detail'] for g in guards))
        self.research_conditions.setPlainText(f"{research['title']} / {research['focus']}\n\n报告范围：{report['scope']}\n\n"
            + '\n\n'.join(f"{g['title']} · {g['state']}\n{g['detail']}" for g in guards)
            + '\n\n输入原料、已实现计算、因子研究结果与回测引擎分别验收。未登记产物不会显示已计算。'
              '\n扫描不补采或修改业务值；数据改变后须重新检查。未核验的子集不能自动视为可用。')
        if report.get('inventory'):
            self.inventory_view.render(report['inventory'])
        if report.get('cache_note'):
            self.test_summary.setToolTip(report['cache_note'])
            if '已读取 Redis' in report['cache_note']:
                self.summary.setText(self.summary.text() + ' 显示历史缓存；最新状态请重新检查。')
        if report.get('checking'):
            self.summary.setText(self.summary.text() +
                f" · 已检查 {report['checked_requirements']} / {report['total_requirements']} 项"
                + (f" · 当前：{plain(report['current_requirement'])}" if report['current_requirement'] else ''))
        verified = report['test_evidence'].startswith('本版本测试证据：')
        self.test_summary.setText('开发证据：本版本发布测试已通过（不计入数据完成分母）。' if verified
                                  else '开发证据：本版本发布测试待核验；与下方业务数据状态分别呈现。')
        self.test_summary.setToolTip(report['test_evidence'] + '\n' + report.get('cache_note', ''))
        self.copy_button.setEnabled(True)
        self.filter_rows()
        if self.preferred:
            for index, entry in enumerate(self.visible_entries):
                if entry['id'] == self.preferred['selected']:
                    self.table.selectRow(index)
                    break
            self.preferred = None

    def filter_rows(self):
        query = self.search.text().strip().casefold()
        self.visible_entries = [r for r in self.entries
            if matches_view(r, self.directory.view.currentData())
            and (not self.kind.currentData() or r['kind'] == self.kind.currentData())
            and (not self.category.currentData() or r['category'] == self.category.currentData())
            and (not self.priority.currentData() or r['priority'] == self.priority.currentData())
            and (not self.state.currentData() or r['status'] == self.state.currentData())
            and query in plain(f"{r['title']} {r['source']} {r['specification'].fields} {r['specification'].purpose}").casefold()]
        rows(self.table, [[plain(r['title']), f"{'必需' if r.get('required', True) else '本次不需要'} · {r['kind']}",
                          r['source'], r.get('collection_state', r['assessment']['integrity']),
                          r['assessment']['quality'], r['assessment']['use_state']]
                          for r in self.visible_entries], keys=[r['id'] for r in self.visible_entries])
        self.directory.render(self.entries, len(self.visible_entries))
        if self.visible_entries and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.show_detail()

    def copy_report(self):
        if not self.report:
            return
        lines = ['数据准备检查报告', self.summary.text(), self.research_summary.toolTip()]
        for entry in self.entries:
            lines.append(f"\n【{entry['kind']}】{plain(entry['title'])}：{STATUS.get(entry['status'], entry['status'])}\n"
                         f"开发验收：{entry['assessment']['development']}；采集完整性：{entry['assessment']['integrity']}；"
                         f"来源质量：{entry['assessment']['quality']}；用途：{entry['assessment']['use_state']}")
            lines.append('本轮检查范围：' + entry['scope'])
            lines.append('本项范围：' + plain(entry['specification'].boundary))
            if entry['blockers']:
                lines.append('需要先准备：' + '、'.join(plain(v) for v in entry['blockers']))
            for item in entry['checks']:
                if item['status'] != 'pass':
                    label = '用途限制' if not item.get('blocking', True) else item.get('dimension', item['phase'])
                    lines.append(f"- {label} / {check_title(item)}：{finding(item)} 接下来：{action(item)}")
        QApplication.clipboard().setText('\n'.join(lines))



class PreparationUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.preparation', '数据准备进度界面', provides=('ui.pages.preparation',),
                              description='要准备的数据、当前进度和剩余工作')

    def create_pages(self):
        return (PageContribution('preparation', '数据准备', PreparationPage, '数据准备',
                                 top_level=True, cache_policy='lru'),)
