"""Archived task directory and restore commands."""
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from empire.plugins.ui.common import Pager, accessible, bind_find, hint, rows, table

from .base import CollectionView


class ArchivedTasksPage(CollectionView):
    section = 'archived'

    def build_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索归档任务名称、ID、来源')
        self.search.setMaxLength(100)
        self.search.setClearButtonEnabled(True)
        accessible(self.search, '搜索归档任务')
        bind_find(page, self.search)
        self.search.textChanged.connect(self.filters_changed)
        layout.addWidget(self.search)
        self.tasks = table(['任务', '来源', '分类', '原执行计划', '原启停状态', '任务ID'])
        self.tasks.setAccessibleName('归档任务列表')
        self.tasks.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.tasks, 1)
        self.task_pager = Pager()
        self.task_pager.changed.connect(self.change_page)
        layout.addWidget(self.task_pager)
        self.empty = hint('没有归档任务。可在采集任务中选中暂时不用的任务并归档。')
        layout.addWidget(self.empty)
        actions = QHBoxLayout()
        self.restore = QPushButton('还原任务')
        accessible(self.restore, '还原选中的归档任务')
        self.restore.clicked.connect(self.restore_selected)
        actions.addWidget(self.restore)
        actions.addStretch()
        layout.addLayout(actions)
        self.feedback_label = hint('选中任务后还原；原先停用的任务仍保持停用。')
        layout.addWidget(self.feedback_label)
        return page

    @property
    def pager(self):
        return self.task_pager

    def selected(self):
        index = self.tasks.currentRow()
        jobs = (self.data or {}).get('jobs', [])
        return jobs[index] if 0 <= index < len(jobs) else None

    def restore_selected(self):
        job = self.selected()
        if job:
            self.submit('set_archived', job['id'], False)

    def _query_args(self):
        return ('tasks', self.search.text(), '', '', 'archived', self.offset, 25)

    def summary_text(self):
        return f"{self.data.get('total', 0)} 个归档任务"

    def render_content(self):
        jobs = self.data['jobs']
        values = []
        for job in jobs:
            policy = job['policy']
            plan = {'manual': '仅手动', 'daily': '每天 ' + policy['daily_time'],
                    'interval': f"结束后 {policy['interval_seconds']:,} 秒"}[policy['mode']]
            values.append([job['name'], job['source_name'], job['category'], plan,
                           '已启用' if policy['enabled'] else '已停用', job['id']])
        rows(self.tasks, values, keys=[job['id'] for job in jobs])
        self.empty.setVisible(not jobs)

    def _update_buttons(self):
        if hasattr(self, 'restore'):
            self.restore.setEnabled(bool(self.selected() and self.action is None))

    def action_feedback(self, method):
        return self.feedback_label
