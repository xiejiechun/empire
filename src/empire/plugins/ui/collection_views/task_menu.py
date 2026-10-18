"""Source/task navigation with stable selection and expansion."""
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
)

from empire.plugins.ui.common import STATUS

ROLE = Qt.ItemDataRole.UserRole


def task_state(job):
    if job['policy'].get('archived'):
        return 'archived'
    if not job['policy']['enabled'] and not job['active']:
        return 'disabled'
    return job['progress'].get('status', 'running') if job['active'] else job['last_status']


def schedule_text(policy):
    text = {'manual': '仅手动', 'interval': f"结束后 {policy['interval_seconds']:,} 秒",
            'daily': f"每天 {policy['daily_time']}"}[policy['mode']]
    return text if policy['enabled'] else '已停用 · ' + text


class TaskItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() + 12))
        return size


class TaskMenu(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('taskMenu')
        self.setItemDelegate(TaskItemDelegate(self))
        self.setHeaderLabels(['数据来源 / 采集任务', '状态'])
        self.setAccessibleName('两级采集任务菜单')
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setToolTip('Shift 连选、Ctrl 多选具体任务，再点击批量启动或批量停止；来源标题不计入任务。')
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setIndentation(18)
        self.setMinimumHeight(180)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(False)
        self._signature = None
        self.task_items = {}
        self.group_items = {}

    def selected_id(self):
        item = self.currentItem()
        return item.data(0, ROLE)[1] if item and item.parent() else None

    def selected_ids(self):
        selected = {item.data(0, ROLE)[1] for item in self.selectedItems() if item.parent()}
        return [ident for ident in self.task_items if ident in selected]

    def render_jobs(self, jobs, preferred_id, force_selection=False):
        item = self.currentItem()
        previous_key = item.data(0, ROLE) if item else None
        selected_ids = self.selected_ids()
        collapsed = {key for key, group in self.group_items.items() if not group.isExpanded()}
        scroll = self.verticalScrollBar().value()
        signature = tuple((job['rate_group'], job['id']) for job in jobs)
        rebuilt = signature != self._signature
        self.blockSignals(True)
        if rebuilt:
            self.clear()
            self.task_items, self.group_items = {}, {}
            for job in jobs:
                source = job['rate_group']
                if source not in self.group_items:
                    group = QTreeWidgetItem(self)
                    group.setData(0, ROLE, ('source', source))
                    font = group.font(0)
                    font.setBold(True)
                    group.setFont(0, font)
                    group.setExpanded(source not in collapsed)
                    self.group_items[source] = group
                child = QTreeWidgetItem(self.group_items[source])
                child.setData(0, ROLE, ('task', job['id']))
                self.task_items[job['id']] = child
            self._signature = signature
        for job in jobs:
            child = self.task_items[job['id']]
            child.setText(0, job['name'])
            state = task_state(job)
            child.setText(1, {'disabled': '已停用', 'archived': '已归档'}.get(state, STATUS.get(state, state)))
            child.setToolTip(0, f"{job['name']}\n{job.get('category', '其他')} · {schedule_text(job['policy'])}\n{job['id']}")
            child.setToolTip(1, child.text(1))
            group = self.group_items[job['rate_group']]
            group.setText(0, f"{job.get('source_name', job['rate_group'])}（{group.childCount()} 项）")
        chosen = self.task_items.get(preferred_id)
        if not force_selection and previous_key and previous_key[0] == 'source':
            chosen = self.group_items.get(previous_key[1], chosen)
        if not chosen and jobs:
            chosen = self.task_items[jobs[0]['id']]
        if chosen:
            if rebuilt or force_selection:
                self.setCurrentItem(chosen, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.clearSelection()
                if force_selection or previous_key is None:
                    chosen.setSelected(True)
                else:
                    for ident in selected_ids:
                        if ident in self.task_items:
                            self.task_items[ident].setSelected(True)
                    if previous_key[0] == 'source':
                        chosen.setSelected(True)
            if chosen.parent() and previous_key != chosen.data(0, ROLE):
                chosen.parent().setExpanded(True)
                self.scrollToItem(chosen)
            else:
                self.verticalScrollBar().setValue(scroll)
        self.blockSignals(False)

    def select_task(self, ident):
        item = self.task_items.get(ident)
        if item:
            item.parent().setExpanded(True)
            self.setCurrentItem(item)
            self.scrollToItem(item)
