"""Work progress dashboard with separately measured development and data acceptance."""
import time
from concurrent.futures import CancelledError

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import accessible, bind_find, hint, rows, table, update_options
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.preparation_detail import PreparationDetail
from empire.plugins.ui.preparation_scope import PreparationScopeBar
from empire.plugins.ui.preparation_words import (
    PRIORITY,
    STATUS,
    action,
    check_title,
    finding,
    plain,
)
from empire.plugins.ui.queries import QueryScope


class PreparationPage(QWidget):
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
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel('数据准备 · 进度一览')
        title.setObjectName('pageTitle')
        heading.addWidget(title)
        heading.addStretch()
        self.refresh_button = QPushButton('重新检查')
        self.refresh_button.clicked.connect(self.reload)
        heading.addWidget(self.refresh_button)
        self.copy_button = QPushButton('复制检查记录')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_report)
        heading.addWidget(self.copy_button)
        self.manage = QPushButton('打开采集任务')
        self.manage.clicked.connect(self.open_task)
        self.manage.setEnabled(False)
        heading.addWidget(self.manage)
        layout.addLayout(heading)
        layout.addWidget(hint('每类独立数据由独立采集插件负责，不按网站栏目合并；一个来源即可满足，按声明范围检查。'))
        layout.addWidget(hint('下方用途、证券与日期范围用于三表和分时检查：三表按报告期，分时按交易日。其他数据按来源声明范围核验。改动后点击重新检查。'))
        self.scope_bar = PreparationScopeBar()
        layout.addWidget(self.scope_bar)
        self.summary = hint('正在检查功能和数据……')
        layout.addWidget(self.summary)
        self.test_summary = hint('软件改过后要重新检查，不能拿上次的结果算完成。')
        layout.addWidget(self.test_summary)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索数据名称、内容或用途（Ctrl+F）')
        self.search.setClearButtonEnabled(True)
        accessible(self.search, '搜索需要准备的数据')
        bind_find(self, self.search)
        self.kind = QComboBox()
        self.category, self.priority, self.state = QComboBox(), QComboBox(), QComboBox()
        for combo, name in ((self.kind, '工作类型'), (self.category, '数据分类'), (self.priority, '准备顺序'), (self.state, '准备情况')):
            accessible(combo, name)
            filters.addWidget(combo)
            combo.currentIndexChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.search.textChanged.connect(self.filter_rows)
        layout.addLayout(filters)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = table(['要准备什么', '分类', '开发验收', '采集完整性', '来源质量', '用途条件', '用途可用性'])
        self.table.setAccessibleName('数据准备工作进展')
        for index in (2, 3, 4, 5, 6):
            self.table.setColumnWidth(index, 105)
        self.table.setColumnWidth(6, 150)
        self.table.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(self.table)
        self.detail = PreparationDetail()
        splitter.addWidget(self.detail)
        splitter.setSizes([300, 420])
        layout.addWidget(splitter, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    def page_activated(self):
        self.tick()

    def reload(self):
        self.needs_check = True
        self.tick()

    def save_ui_state(self):
        index = self.table.currentRow()
        return dict(search=self.search.text(), kind=self.kind.currentData(), category=self.category.currentData(),
                    priority=self.priority.currentData(), state=self.state.currentData(),
                    scope=self.scope_bar.save(),
                    selected=self.visible_entries[index]['id'] if 0 <= index < len(self.visible_entries) else None)

    def restore_ui_state(self, state):
        self.search.setText(state['search'])
        self.preferred = state
        if 'scope' in state:
            self.scope_bar.restore(state['scope'])

    def show_detail(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_entries):
            entry = self.visible_entries[index]
            self.detail.render(entry)
            self.manage.setEnabled(bool(entry['project']))
        else:
            self.detail.clear()
            self.manage.setEnabled(False)

    def open_task(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_entries):
            project = self.visible_entries[index]['project']
            if project:
                self.shell.navigate('collection', NavigationContext(task_id=project))

    def render(self, report):
        first_report = not self.entries
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
        if first_report and not self.preferred:
            self.kind.setCurrentIndex(max(0, self.kind.findData('采集')))
        collecting = [r for r in self.entries if r['kind'] == '采集']
        processing = [r for r in self.entries if r['kind'] != '采集']
        self.summary.setText(
            f"采集 {len(collecting)} 项，已做好 {sum(r['complete'] for r in collecting)} 项；"
            f"整理、计算和核对 {len(processing)} 项，已做好 {sum(r['complete'] for r in processing)} 项。"
            f"上次检查：{report['checked_at'][:19].replace('T', ' ')}；范围：{report.get('scope', '来源声明范围')}")
        if report.get('checking'):
            self.summary.setText(self.summary.text() +
                f" · 已检查 {report['checked_requirements']} / {report['total_requirements']} 项"
                + (f" · 当前：{plain(report['current_requirement'])}" if report['current_requirement'] else ''))
        verified = report['test_evidence'].startswith('本版本测试证据：')
        self.test_summary.setText('当前版本的功能测试已有通过记录，数据是否齐全还要逐项看。' if verified
                                  else '当前版本的功能测试结果还不能确认，需要重新运行完整检查。')
        self.test_summary.setToolTip(report['test_evidence'])
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
            if (not self.kind.currentData() or r['kind'] == self.kind.currentData())
            and (not self.category.currentData() or r['category'] == self.category.currentData())
            and (not self.priority.currentData() or r['priority'] == self.priority.currentData())
            and (not self.state.currentData() or r['status'] == self.state.currentData())
            and query in plain(f"{r['title']} {r['specification'].fields} {r['specification'].purpose}").casefold()]
        rows(self.table, [[plain(r['title']), f"{r['category']} · {r['kind']}",
                          *[r['assessment'][k] for k in ('development', 'integrity', 'quality', 'usage', 'use_state')]]
                          for r in self.visible_entries], keys=[r['id'] for r in self.visible_entries])
        if self.visible_entries and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.show_detail()

    def copy_report(self):
        if not self.report:
            return
        lines = ['数据准备进度', self.summary.text()]
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

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            self.refresh_button.setEnabled(True)
            if self.snapshot_future is not None:
                self.query_scope.cancel('preparation_snapshot')
                self.snapshot_future = None
            try:
                self.render(self.query_scope.result('preparation', future))
            except Exception as exc:
                if isinstance(exc, CancelledError):
                    self.needs_check = True
                self.summary.setText(self.query_scope.failure_message(
                    'preparation', '这次没能检查完', redact(exc, self.shell.cfg), stale=bool(self.entries)))
        if self.snapshot_future is not None and self.snapshot_future.done():
            future, self.snapshot_future = self.snapshot_future, None
            try:
                report = self.query_scope.result('preparation_snapshot', future)
                if report is not None and self.future is not None:
                    self.render(report)
            except Exception:
                pass  # The full owned query reports errors; keep the existing list.
        if self.isVisible() and self.future is not None and self.snapshot_future is None and time.monotonic() - self.last_snapshot >= 1:
            self.last_snapshot = time.monotonic()
            self.snapshot_future = self.query_scope.invoke('preparation_snapshot', self.shell.runtime,
                                                           'preparation.query', 'snapshot', self.active_request)
        if self.isVisible() and self.future is None and self.needs_check:
            try:
                request = self.scope_bar.request()
            except ValueError as exc:
                self.summary.setText(str(exc))
                self.needs_check = False
                return
            self.needs_check = False
            self.active_request = request
            self.refresh_button.setEnabled(False)
            self.summary.setText('正在检查；全股票池全历史可能耗时数分钟。当前显示上次结果，不代表本轮通过。')
            self.future = self.query_scope.invoke('preparation', self.shell.runtime, 'preparation.query', 'report', request)


class PreparationUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.preparation', '数据准备进度界面', provides=('ui.pages.preparation',),
                              description='要准备的数据、当前进度和剩余工作')

    def create_pages(self):
        return (PageContribution('preparation', '数据准备', PreparationPage, '数据准备',
                                 top_level=True, cache_policy='lru'),)
