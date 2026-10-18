"""Selection-wide actions, independent of the current task's editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from empire.core.redaction import redact
from empire.plugins.ui.common import hint


class TaskBatch:
    def build_batch_actions(self, layout):
        self.batch_selection = hint('Shift 连选、Ctrl 多选任务')
        layout.addWidget(self.batch_selection)
        row = QHBoxLayout()
        self.batch_start = QPushButton('批量启动')
        self.batch_stop = QPushButton('批量停止')
        self.batch_start.setToolTip('启用选中任务并按已保存配置采集；已运行的跳过，保留未保存草稿。')
        self.batch_stop.setToolTip('停止选中任务并关闭后续计划，保留断点和业务数据。')
        self.batch_start.clicked.connect(lambda: self.execute_batch('start'))
        self.batch_stop.clicked.connect(lambda: self.execute_batch('stop'))
        row.addWidget(self.batch_start)
        row.addWidget(self.batch_stop)
        layout.addLayout(row)
        self.batch_feedback = hint()
        self.batch_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.batch_feedback.setAccessibleName('批量操作结果')
        layout.addWidget(self.batch_feedback)

    def execute_batch(self, operation):
        identifiers = self.task_menu.selected_ids()
        if identifiers:
            self.submit('batch', operation, identifiers)

    def update_batch_buttons(self, ready):
        count = len(self.task_menu.selected_ids())
        self.batch_selection.setText(f'已选 {count} 项 · Shift 连选 / Ctrl 多选')
        for button in (self.batch_start, self.batch_stop):
            button.setEnabled(bool(ready and count))

    def batch_result(self, result):
        rows = result['results']
        counts = {status: sum(row['status'] == status for row in rows)
                  for status in ('success', 'skipped', 'failed')}
        operation = '启动' if result['operation'] == 'start' else '停止'
        summary = f"批量{operation}：成功 {counts['success']}，跳过 {counts['skipped']}，失败 {counts['failed']}"
        names = {job['id']: job['name'] for job in (self.data or {}).get('jobs', [])}
        details = '\n'.join(f"{names.get(row['id'], row['id'])}：{row['message']}" for row in rows)
        self.batch_feedback.setToolTip(redact(details, self.shell.cfg))
        issues = [row for row in rows if row['status'] != 'success']
        preview = [' '.join(f"{names.get(row['id'], row['id'])}：{row['message']}".split())[:160]
                   for row in issues[:3]]
        if len(issues) > 3:
            preview.append(f'另 {len(issues) - 3} 项，请悬停查看完整结果')
        return '\n'.join([summary, *[redact(line, self.shell.cfg) for line in preview]])
