from copy import deepcopy

from PySide6.QtCore import Qt, QTime

from empire.contracts.ui import NavigationContext
from empire.core.redaction import redact
from empire.plugins.ui.common import STATUS, rows, stamp, update_options

from .base import CollectionView
from .network_summary import network_summary
from .task_layout import TaskLayout


class TasksPage(TaskLayout, CollectionView):
    section = "tasks"
    build_view = TaskLayout._tasks_page

    def apply_navigation_context(self, context: NavigationContext):
        if not context.task_id:
            return
        if self.focus_task_id is None:
            self.focus_return_offset = self.offset
        self.focus_task_id = context.task_id
        self.loaded_id = context.task_id
        self.focus_notice.setText(f"已从数据页面定位采集任务：{context.task_id}。原筛选和分页保持不变。")
        self.focus_notice.show()
        self.clear_focus_button.show()
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
        super().filters_changed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "task_split"):
            narrow = self.width() < 950
            orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
            self._arrange_task_filters(narrow)
            for column in (1, 2, 4):
                self.jobs.setColumnHidden(column, self.width() < 720)
            if self.task_split.orientation() != orientation:
                self.task_split.setOrientation(orientation)
                self.task_inspector.setMinimumWidth(0 if orientation == Qt.Orientation.Vertical else 320)
                self.task_inspector.setMinimumHeight(140)
                self.task_split.setSizes([280, 330] if orientation == Qt.Orientation.Vertical else [650, 370])

    def selected(self):
        if not self.data or not 0 <= self.jobs.currentRow() < len(self.data["jobs"]):
            return None
        return self.data["jobs"][self.jobs.currentRow()]

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
        if not job:
            return
        self.job_baselines[job["id"]] = deepcopy(job["policy"])
        if self.loaded_id != job["id"]:
            self.loaded_id = job["id"]
            self._load_job(self.job_drafts.get(job["id"], job["policy"]))
            self.task_feedback.setText("有未保存修改，采集仍使用已保存的计划" if job["id"] in self.job_drafts else "")
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
        route_mode = ("direct" if not policy.get("use_proxy", False) else
                      "proxy_fallback" if policy.get("proxy_fallback", True) else "proxy_only")
        self.route_mode.setCurrentIndex(self.route_mode.findData(route_mode))
        self._loading = False
        self.mode_changed()

    def mode_changed(self):
        mode = self.mode.currentData()
        self.job_form.setRowVisible(self.interval, mode == "interval")
        self.job_form.setRowVisible(self.daily, mode == "daily")
        self.plan_note.setText({
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
        self.fresh_button.setToolTip(job.get("fresh_description", "创建新批次；已归档数据保留。"))
        self.detail.setText(f"{job['description']} · 网站：{job['rate_group']}\n{network_summary(job)}")
        progress = job["progress"]
        state = progress.get("status", "running") if job["active"] else job["last_status"]
        self.run_button.setText("继续采集" if state in ("paused", "error") else "立即采集")
        self.run_button.setToolTip("先勾选“启用任务”并保存执行计划。" if not job["policy"]["enabled"]
                                  else "有未完成批次时从断点继续，否则开始新的采集。")
        self.progress.setRange(0, 100)
        if job["active"]:
            collected, expected = progress.get("collected", 0), progress.get("expected_count", 0)
            text = (f"{STATUS.get(state, state)} · {collected:,} / {expected:,} 条" if expected
                    else f"{STATUS.get(state, state)} · 已处理 {collected:,} 条")
            if progress.get("current_month"):
                text += f" · 当前 {progress['current_month']} · {progress.get('pages', 0)} / {progress.get('total_months', 0)} 个月"
            if expected:
                self.progress.setValue(min(100, int(collected * 100 / expected)))
            else:
                self.progress.setRange(0, 0)
        else:
            latest = next((h for h in self.data["history"] if h["task_id"] == job["id"]), None)
            self.progress.setValue(100 if state == "complete" else 0)
            text = STATUS.get(state, state)
            if latest:
                count = latest.get("result", {}).get("collected")
                if count is not None:
                    text += f" · {count:,} 条"
                text += f" · 最近结束 {stamp(latest.get('finished_at'))}"
            else:
                text += " · 尚无运行记录"
        self.progress_label.setText(text)
        error = redact(job.get("error", ""), self.shell.cfg)
        self.progress_label.setToolTip(error)
        if error:
            self.detail.setText(self.detail.text() + "\n失败原因：" + error[:160]
                                + ("……请到运行记录查看完整详情" if len(error) > 160 else ""))

    def _update_buttons(self):
        ready = self.data is not None and self.action is None
        for button in self.buttons:
            button.setEnabled(ready)
        job = self.selected()
        for button in self.run_buttons:
            button.setEnabled(bool(ready and job and job["policy"]["enabled"] and not job["active"]))
        self.pause_button.setEnabled(bool(ready and job and (job["policy"]["enabled"] or job["active"])))
        self.save_button.setEnabled(bool(ready and self.loaded_id in self.job_drafts))
        self.reset_button.setEnabled(bool(ready and self.loaded_id in self.job_drafts))

    def render_content(self):
        jobs = self.data["jobs"]
        update_options(self.task_category, self.data.get("categories", []), "全部分类")
        update_options(self.task_source, self.data.get("sources", []), "全部来源")
        self.task_empty.setVisible(not jobs)
        self.task_inspector.setEnabled(bool(jobs))
        if not jobs:
            self.loaded_id = None
            self.task_name.setText("未选择任务")
            self.detail.clear()
            if self.focus_task_id and self.data.get("focus_missing"):
                self.focus_notice.setText(f"关联采集任务不可用：{self.focus_task_id}")
        selected = next((i for i, job in enumerate(jobs) if job["id"] == self.loaded_id), 0)
        self.jobs.blockSignals(True)
        values = []
        for job in jobs:
            policy = job["policy"]
            plan = {"manual": "仅手动", "interval": f"结束后 {policy['interval_seconds']} 秒",
                    "daily": f"每天 {policy['daily_time']}"}[policy["mode"]]
            if not policy["enabled"]:
                plan = "已停用 · " + plan
            if not policy.get("use_proxy"):
                plan += " · 本机直连"
            elif policy.get("proxy_fallback", True):
                plan += " · 代理优先"
            else:
                plan += " · 仅代理"
            state = job["progress"].get("status", "running") if job["active"] else job["last_status"]
            values.append([job["name"], f"{job.get('source_name', job['rate_group'])} / {job.get('category', '其他')}",
                           plan, STATUS.get(state, state) if policy["enabled"] else "已停用", stamp(job["next_due"])])
        rows(self.jobs, values, keys=[job["id"] for job in jobs])
        if jobs:
            self.jobs.selectRow(selected)
        self.jobs.blockSignals(False)
        self.select_job()

    @property
    def pager(self):
        return self.task_pager

    def initialize_state(self):
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
