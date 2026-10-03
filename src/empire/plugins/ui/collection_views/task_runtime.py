"""Consistent read-only task detail fields; never infer archived counts."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from empire.core.redaction import redact
from empire.plugins.ui.common import STATUS, hint, stamp

from .network_summary import network_summary
from .task_menu import schedule_text


class TaskRuntime(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.setObjectName('taskRuntime')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        owner.runtime_description = hint()
        layout.addWidget(owner.runtime_description)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        layout.addLayout(self.grid)
        layout.addStretch()
        self.groups = []
        owner.runtime_fields, owner.runtime_forms = {}, {}
        for title, fields in (
            ('状态与进度', [('status', '运行状态'), ('count', '本轮 / 最近记录'), ('units', '核验单元'),
                          ('current', '当前位置'), ('frontier', '连续进度'), ('failed', '失败单元'),
                          ('unavailable', '来源暂无详情'), ('archive', '归档确认')]),
            ('时间与计划', [('plan', '已保存计划'), ('next', '下次执行'), ('start', '最近开始'),
                          ('finish', '最近结束')]),
            ('网络', [('network', '网络情况')]),
            ('异常', [('error', '失败原因')]),
        ):
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setContentsMargins(10, 10, 10, 10)
            form.setVerticalSpacing(8)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for key, label in fields:
                value = QLabel('—')
                value.setWordWrap(True)
                value.setMinimumWidth(0)
                value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                value.setTextFormat(Qt.TextFormat.PlainText)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setAccessibleName(label)
                form.addRow(value) if key in ('network', 'error') else form.addRow(label, value)
                owner.runtime_fields[key], owner.runtime_forms[key] = value, form
            if title == '状态与进度':
                owner.progress = QProgressBar()
                owner.progress.setTextVisible(False)
                owner.progress.setFixedHeight(8)
                owner.progress.setToolTip('采集或入队比例；整轮归档确认后才显示已完成。')
                form.addRow(owner.progress)
            self.groups.append(group)
        self.columns = 0
        self.reflow()

    def reflow(self):
        columns = 2 if self.width() >= 620 else 1
        if columns == self.columns:
            return
        self.columns = columns
        for group in self.groups:
            self.grid.removeWidget(group)
        for index, group in enumerate(self.groups):
            if columns == 2 and index < 2:
                self.grid.addWidget(group, 0, index, alignment=Qt.AlignmentFlag.AlignTop)
            else:
                self.grid.addWidget(group, index if columns == 1 else index - 1, 0, 1, columns)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1 if columns == 2 else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


def build_runtime(owner):
    owner.runtime_view = TaskRuntime(owner)
    return owner.runtime_view


def render_runtime(owner, job):
    progress = job.get('progress', {}) if job['active'] else {}
    latest = next((h for h in owner.data['history'] if h['task_id'] == job['id']), None)
    result = progress if job['active'] else (latest or {}).get('result', {})
    state = progress.get('status', 'running') if job['active'] else job['last_status']
    owner.run_button.setText('继续采集' if state in ('paused', 'error') else '立即采集')
    owner.run_button.setToolTip('先启用任务并保存执行计划。' if not job['policy']['enabled']
                               else '有未完成批次时从断点继续，否则开始新的采集。')
    collected = result.get('queued_records', result.get('collected'))
    expected = result.get('expected_count', 0)
    record_name = result.get('record_name', '条')
    count = '暂无数量统计' if collected is None else f"{collected:,}" + (
        f" / {expected:,} {record_name}" if expected else ' ' + record_name)
    if 'queued_records' in result:
        count = '已入队 ' + count
    units = '—'
    if result.get('unit_name') and 'completed_units' in result:
        units = f"{result['completed_units']:,} / {result.get('total_units', 0):,} {result['unit_name']}"
    elif 'processed_units' in result:
        units = f"{result['processed_units']:,} / {result.get('total_units', 0):,} 个证券"
    elif result.get('total_months'):
        units = f"{result.get('pages', 0):,} / {result['total_months']:,} 个月"
    elif 'pages' in result:
        units = f"已处理 {result['pages']:,} 页" + (f" · 本轮范围 {result['total_units']:,} 个证券" if result.get('total_units') else '')
    active = job.get('active')
    started = active.get('started_at') if isinstance(active, dict) else None
    error = redact(job.get('error') or (latest or {}).get('error') or '', owner.shell.cfg)
    if job['active']:
        error = redact(job.get('error', ''), owner.shell.cfg)
    archive = ('等待本轮归档确认' if state == 'awaiting_archive' else
               '整轮已确认，可查询' if state == 'complete' else
               '尚未确认本轮完成；已归档部分可查询')
    values = dict(status=STATUS.get(state, state), count=count, units=units,
                  current=result.get('current_security') or result.get('current_date') or result.get('current_month') or '—',
                  frontier=(f"连续已入队 {result['continuous_collected']:,} 条" if 'continuous_collected' in result else '—'),
                  failed=(f"失败 {result['failed_units']:,} {result.get('unit_name', '个证券')}"
                          if 'failed_units' in result else '—'),
                  unavailable=(f"{result['details_unavailable']:,} 条" if 'details_unavailable' in result else '—'),
                  archive=archive, plan=schedule_text(job['policy']),
                  next='本轮结束后安排' if job['active'] else stamp(job.get('next_due')),
                  start=stamp(started or (latest or {}).get('started_at')),
                  finish='本轮运行中' if job['active'] else stamp((latest or {}).get('finished_at')),
                  network=network_summary(job), error=error or '暂无运行错误；来源质量请到数据准备查看。')
    for key, value in values.items():
        owner.runtime_fields[key].setText(str(value))
    for key, field in [('frontier', 'continuous_collected'), ('failed', 'failed_units'),
                       ('unavailable', 'details_unavailable')]:
        owner.runtime_forms[key].setRowVisible(owner.runtime_fields[key], field in result)
    owner.progress.setRange(0, 100)
    if job['active'] and expected and collected is not None:
        owner.progress.setValue(min(100, int(collected * 100 / expected)))
    elif job['active']:
        owner.progress.setRange(0, 0)
    else:
        owner.progress.setValue(100 if state == 'complete' else 0)
