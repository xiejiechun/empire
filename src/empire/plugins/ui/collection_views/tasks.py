from copy import deepcopy

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel

from empire.contracts.ui import NavigationContext
from empire.plugins.ui.common import hint, update_options

from .base import CollectionView
from .task_layout import TaskLayout
from .task_runtime import render_runtime


class TasksPage(TaskLayout, CollectionView):
    section = "tasks"
    build_view = TaskLayout._tasks_page

    def heightForWidth(self, width):
        # Detail tabs already scroll. Their preferred text height must not expand
        # the shell's entire page and push the menu/actions/footer off screen.
        return self.minimumSizeHint().height()

    def build_heading(self, layout):
        row = QHBoxLayout()
        self.title = QLabel('采集任务')
        self.title.setObjectName('compactPageTitle')
        self.summary = hint('正在连接采集管理服务……')
        self.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.title)
        row.addWidget(self.summary, 1)
        layout.addLayout(row)

    def apply_navigation_context(self, context: NavigationContext):
        if not context.task_id:
            return
        if self.focus_task_id is None:
            self.focus_return_offset = self.offset
        self.focus_task_id = context.task_id
        self.focus_notice.setText(f"已从数据页面定位采集任务：{context.task_id}。原筛选和分页保持不变。")
        self.focus_notice.show()
        self.clear_focus_button.show()
        self.focus_panel.show()
        if self.query is not None:
            self.query_scope.cancel("workspace")
        self.query = None
        self.data = None
        self.next_query = 0
        self._update_buttons()

    def clear_navigation_focus(self):
        if self.focus_task_id is None:
            return
        self.focus_task_id = None
        self.offset = self.focus_return_offset
        self.focus_notice.hide()
        self.clear_focus_button.hide()
        self.focus_panel.hide()
        if self.query is not None:
            self.query_scope.cancel("workspace")
        self.query = None
        self.data = None
        self.next_query = 0
        self._update_buttons()

    def filters_changed(self):
        self.focus_task_id = None
        if hasattr(self, "focus_notice"):
            self.focus_notice.hide()
            self.clear_focus_button.hide()
            self.focus_panel.hide()
        super().filters_changed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "task_split"):
            narrow = self.width() < 950
            self.task_menu.setMinimumHeight(110 if narrow else 180)
            orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
            self._arrange_task_filters(narrow)
            if self.task_split.orientation() != orientation or not self._task_layout_ready:
                self._task_layout_ready = True
                self.task_split.setOrientation(orientation)
                self.task_split.setSizes([170, 400] if narrow else [320, max(320, self.width() - 320)])

    def selected(self):
        ident = self.task_menu.selected_id()
        return next((job for job in (self.data or {}).get("jobs", []) if job["id"] == ident), None)

    def _policy(self):
        route_mode = self.route_mode.currentData()
        return {"enabled": self.enabled.isChecked(), "mode": self.mode.currentData(),
                "interval_seconds": self.interval.value(),
                "daily_time": self.daily.time().toString("HH:mm"),
                "request_retries": self.retries.value(),
                "use_proxy": route_mode != "direct",
                "proxy_fallback": route_mode == "proxy_fallback"}

    def select_job(self):
        job = self.selected()
        self.task_inspector.setEnabled(bool(job))
        self.detail_stack.setCurrentIndex(1 if job else 0)
        if not job:
            self.task_name.setText("展开来源并选择具体任务")
            self.detail.clear()
            self.runtime_description.clear()
            self.operation_feedback.setText("采集操作使用已保存的设置；暂停后保留断点。")
            for field in self.runtime_fields.values():
                field.setText("—")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self._update_buttons()
            return
        self.job_baselines[job["id"]] = deepcopy(job["policy"])
        if self.loaded_id != job["id"]:
            self.loaded_id = job["id"]
            self._load_job(self.job_drafts.get(job["id"], job["policy"]))
            self.task_feedback.setText("有未保存修改，采集仍使用已保存的计划" if job["id"] in self.job_drafts else "")
            self.operation_feedback.setText("采集操作使用已保存的设置；暂停后保留断点。")
        elif job["id"] not in self.job_drafts and self._policy() != job["policy"]:
            self._load_job(job["policy"])
        self._render_job_detail(job)
        self._update_buttons()

    def _load_job(self, policy):
        self._loading = True
        self.enabled.setChecked(policy["enabled"])
        self.mode.setCurrentIndex(self.mode.findData(policy["mode"]))
        self.interval.setValue(policy["interval_seconds"])
        self.daily.setTime(QTime.fromString(policy["daily_time"], "HH:mm"))
        self.retries.setValue(policy["request_retries"])
        route_mode = ("direct" if not policy.get("use_proxy", True) else
                      "proxy_fallback" if policy.get("proxy_fallback", True) else "proxy_only")
        self.route_mode.setCurrentIndex(self.route_mode.findData(route_mode))
        self._loading = False
        self.mode_changed()

    def mode_changed(self):
        mode = self.mode.currentData()
        job = self.selected()
        rule = job.get('execution_rule') if job else None
        self.job_form.setRowVisible(self.mode, not bool(rule))
        self.job_form.setRowVisible(self.interval, not rule and mode == "interval")
        self.job_form.setRowVisible(self.daily, not rule and mode == "daily")
        self.plan_note.setText(rule or {
            "manual": "仅在点击采集按钮时执行，不会自动启动。",
            "interval": "当前运行结束后开始计时；同一任务不会重复并行启动。",
            "daily": "每天按北京时间执行；运行中遇到下一次计划时不会重复启动。",
        }.get(mode, ""))

    def job_edited(self):
        if self._loading or not self.loaded_id:
            return
        policy = self._policy()
        saving = bool(self.action_context and self.action_context[0] == "configure"
                      and self.action_context[1][0] == self.loaded_id)
        if saving or policy != self.job_baselines.get(self.loaded_id):
            self.job_drafts[self.loaded_id] = policy
            self.task_feedback.setText("有未保存修改，采集仍使用已保存的计划")
        else:
            self.job_drafts.pop(self.loaded_id, None)
            self.task_feedback.setText("与已保存设置一致")
        self._update_buttons()

    def reset_job(self):
        if self.loaded_id in self.job_baselines:
            self.job_drafts.pop(self.loaded_id, None)
            self._load_job(self.job_baselines[self.loaded_id])
            self.task_feedback.setText("已撤销未保存修改")
            self._update_buttons()

    def execute(self, method, fresh):
        job = self.selected()
        if job:
            self.submit(method, job["id"], *(() if fresh is None else (fresh,)))

    def save_job(self):
        job = self.selected()
        if job:
            self.submit("configure", job["id"], self._policy())

    def _render_job_detail(self, job):
        self.task_name.setText(job["name"])
        self.task_name.setToolTip(job['id'])
        self.fresh_button.setToolTip(job.get("fresh_description", "创建新批次；已归档数据保留。"))
        self.detail.setText(f"{job.get('source_name', job['rate_group'])} · {job.get('category', '其他')}")
        self.runtime_description.setText(job['description'])
        render_runtime(self, job)

    def _update_buttons(self):
        message = self.operation_feedback.text()
        self.operation_feedback.setVisible(bool(message) and message != "采集操作使用已保存的设置；暂停后保留断点。")
        ready = self.data is not None and self.action is None
        for button in self.buttons:
            button.setEnabled(ready)
        job = self.selected()
        for button in self.run_buttons:
            button.setEnabled(bool(ready and job and job["policy"]["enabled"] and not job["active"]))
        self.pause_button.setEnabled(bool(ready and job and (job["policy"]["enabled"] or job["active"])))
        self.save_button.setEnabled(bool(ready and job and self.loaded_id in self.job_drafts))
        self.reset_button.setEnabled(bool(ready and job and self.loaded_id in self.job_drafts))

    def render_content(self):
        jobs = self.data["jobs"]
        update_options(self.task_category, self.data.get("categories", []), "全部分类")
        update_options(self.task_source, self.data.get("sources", []), "全部来源")
        self.task_source.blockSignals(True)
        for index in range(1, self.task_source.count()):
            ident = self.task_source.itemData(index)
            self.task_source.setItemText(index, self.data.get("source_names", {}).get(ident, ident))
        self.task_source.blockSignals(False)
        self.task_empty.setVisible(not jobs)
        if not jobs and self.focus_task_id and self.data.get("focus_missing"):
            self.focus_notice.setText(f"关联采集任务不可用：{self.focus_task_id}")
        self.task_menu.render_jobs(jobs, self.focus_task_id or self.loaded_id, bool(self.focus_task_id))
        self.select_job()

    @property
    def pager(self):
        return self.task_pager

    def initialize_state(self):
        self._task_layout_ready = False
        self.loaded_id = None
        self.job_drafts, self.job_baselines = {}, {}
        self.focus_task_id = None
        self.focus_return_offset = 0

    def _query_args(self):
        return ("tasks", self.task_search.text(), self.task_category.currentData(),
                self.task_source.currentData(), self.task_status.currentData(),
                0 if self.focus_task_id else self.offset, 25, "", self.focus_task_id or "")

    def summary_text(self):
        jobs = self.data["jobs"]
        counts = self.data.get("counts", {})
        prefix = "已定位关联任务 · " if self.data.get("focused_task_id") else ""
        return (prefix + f"{counts.get('total', len(jobs))} 个采集任务 · "
                f"{counts.get('running', sum(bool(j['active']) for j in jobs))} 个执行中 · "
                f"{counts.get('error', 0)} 个失败 · {counts.get('disabled', 0)} 个停用")

    def action_feedback(self, method):
        return self.task_feedback if method == "configure" else self.operation_feedback

    def apply_action_result(self, method, args, text):
        if method == "configure":
            ident, policy = args
            self.job_baselines[ident] = deepcopy(policy)
            if self.data:
                for job in self.data["jobs"]:
                    if job["id"] == ident:
                        job["policy"] = deepcopy(policy)
            current = self._policy() if self.loaded_id == ident else self.job_drafts.get(ident, policy)
            if current == policy:
                self.job_drafts.pop(ident, None)
            else:
                self.job_drafts[ident] = current
            if ident in self.job_drafts:
                text += "；之后的修改尚未保存"
        return text
