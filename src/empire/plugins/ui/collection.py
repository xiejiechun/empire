from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import QTime, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from empire.core.config import redact
from empire.plugins.collection.control import CHINA

STATUS = {"idle": "待执行", "running": "执行中", "collecting": "正在采集",
          "paused": "已暂停", "complete": "已完成", "error": "失败",
          "awaiting_archive": "等待归档", "stopped": "已停止"}
SECTIONS = {
    "tasks": ("采集任务", "设置执行计划、开始采集与恢复断点，在这里统一管理。"),
    "sites": ("网站频控", "统一控制各网站的请求速度，同一网站组内的所有采集任务共享限制。"),
    "history": ("运行记录", "采集、归档与错误分别查看；仅存 Redis，按项目独立限量保留。"),
}


def stamp(value):
    return datetime.fromtimestamp(value, CHINA).strftime("%m-%d %H:%M:%S") if value else "—"


def elapsed(start, finish):
    if start is None or finish is None:
        return "—"
    seconds = max(0, int(finish - start))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(42)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(False)
    return widget


def rows(widget, values):
    widget.setRowCount(len(values))
    for i, row in enumerate(values):
        for j, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(i, j, item)


def hint(text=""):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class CollectionPage(QWidget):
    def __init__(self, shell, section="tasks"):
        super().__init__()
        if section not in SECTIONS:
            raise ValueError(f"Unknown collection section: {section}")
        self.shell, self.section = shell, section
        self.query = self.action = self.action_context = None
        self.data = None
        self.loaded_id = self.site_loaded = None
        self.job_drafts, self.site_drafts = {}, {}
        self.job_baselines, self.site_baselines = {}, {}
        self._loading = False
        self.history_records = []
        self.history_selection = None
        self.buttons, self.run_buttons = [], []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.title = QLabel(SECTIONS[section][0])
        self.title.setObjectName("pageTitle")
        layout.addWidget(self.title)
        layout.addWidget(hint(SECTIONS[section][1]))
        self.summary = hint("正在连接采集管理服务……")
        layout.addWidget(self.summary)
        self.tabs = QStackedWidget()
        self.tabs.addWidget(self._tasks_page())
        self.tabs.addWidget(self._sites_page())
        self.tabs.addWidget(self._history_page())
        self.tabs.setCurrentIndex(tuple(SECTIONS).index(section))
        layout.addWidget(self.tabs, 1)
        self.feedback = self.site_feedback if section == "sites" else self.task_feedback
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(700)
        self._update_buttons()

    def _tasks_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.jobs = table(["采集任务", "已保存的执行计划", "状态", "下次执行 · 北京时间"])
        self.jobs.setMaximumHeight(146)
        self.jobs.setMinimumHeight(88)
        self.jobs.itemSelectionChanged.connect(self.select_job)
        layout.addWidget(self.jobs)
        group = QGroupBox("当前任务")
        box = QVBoxLayout(group)
        self.task_name = QLabel("请选择采集任务")
        self.task_name.setObjectName("sectionTitle")
        box.addWidget(self.task_name)
        self.detail = hint()
        box.addWidget(self.detail)
        self.progress_label = QLabel("等待任务状态")
        box.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        box.addWidget(self.progress)
        actions = QHBoxLayout()
        self.run_button = QPushButton("立即采集")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(lambda: self.execute("run", False))
        self.fresh_button = QPushButton("从头重新采集")
        self.fresh_button.setToolTip("重新开始采集；不会删除已归档业务数据。")
        self.fresh_button.clicked.connect(lambda: self.execute("run", True))
        self.pause_button = QPushButton("暂停任务与计划")
        self.pause_button.setToolTip("暂停当前采集并关闭后续计划，保留断点。恢复前需启用任务并保存。")
        self.pause_button.clicked.connect(lambda: self.execute("pause", None))
        self.run_buttons = [self.run_button, self.fresh_button]
        self.buttons.extend([*self.run_buttons, self.pause_button])
        for button in [*self.run_buttons, self.pause_button]:
            actions.addWidget(button)
        actions.addStretch()
        box.addLayout(actions)
        self.operation_feedback = hint("采集操作使用已保存的设置；暂停后保留断点。")
        box.addWidget(self.operation_feedback)
        layout.addWidget(group)
        group = QGroupBox("执行计划")
        self.job_form = QFormLayout(group)
        self.job_form.setVerticalSpacing(12)
        self.enabled = QCheckBox("启用任务，允许手动采集和计划执行")
        self.mode = QComboBox()
        for label, value in [("仅手动执行", "manual"), ("固定间隔", "interval"), ("每天定时", "daily")]:
            self.mode.addItem(label, value)
        self.interval = QSpinBox()
        self.interval.setRange(1, 43200)
        self.interval.setSuffix(" 分钟")
        self.daily = QTimeEdit()
        self.daily.setDisplayFormat("HH:mm")
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setSuffix(" 次")
        self.job_form.addRow(self.enabled)
        self.job_form.addRow("执行方式", self.mode)
        self.job_form.addRow("每次结束后等待", self.interval)
        self.job_form.addRow("每日时间 · 北京时间", self.daily)
        self.job_form.addRow("单次请求失败重试", self.retries)
        self.plan_note = hint()
        self.job_form.addRow(self.plan_note)
        save_row = QHBoxLayout()
        self.save_button = QPushButton("保存执行计划")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save_job)
        self.reset_button = QPushButton("撤销修改")
        self.reset_button.clicked.connect(self.reset_job)
        self.buttons.extend([self.save_button, self.reset_button])
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.reset_button)
        save_row.addStretch()
        self.job_form.addRow(save_row)
        self.task_feedback = hint()
        self.job_form.addRow(self.task_feedback)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode.currentIndexChanged.connect(self.job_edited)
        self.enabled.toggled.connect(self.job_edited)
        self.interval.valueChanged.connect(self.job_edited)
        self.daily.timeChanged.connect(self.job_edited)
        self.retries.valueChanged.connect(self.job_edited)
        layout.addWidget(group)
        layout.addWidget(hint("相同内容跳过写库。只重启应用可续跑；Redis 或电脑重启会丢失待归档数据、计划和断点。"))
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        self.mode_changed()
        return scroll

    def _sites_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(hint("任务执行计划决定“多久采集一次”；网站频控决定“一次采集中请求有多快”。"))
        self.sites = table(["网站组", "共享的域名范围", "请求最小间隔", "并发上限"])
        self.sites.setMaximumHeight(240)
        self.sites.itemSelectionChanged.connect(self.select_site)
        layout.addWidget(self.sites)
        group = QGroupBox("网站组设置")
        form = QFormLayout(group)
        form.setVerticalSpacing(14)
        self.site_scope = hint("请选择网站组")
        form.addRow(self.site_scope)
        self.site_interval = QSpinBox()
        self.site_interval.setRange(100, 60000)
        self.site_interval.setSuffix(" 毫秒")
        self.site_interval.setSingleStep(100)
        self.site_interval.valueChanged.connect(self.site_edited)
        form.addRow("请求最小间隔", self.site_interval)
        form.addRow(hint("1,000 毫秒 = 1 秒。重试请求同样计入；各插件不能单独绕过此限制。"))
        save_row = QHBoxLayout()
        self.site_save = QPushButton("保存网站频控")
        self.site_save.setObjectName("primary")
        self.site_save.clicked.connect(self.save_site)
        self.site_reset = QPushButton("撤销修改")
        self.site_reset.clicked.connect(self.reset_site)
        self.buttons.extend([self.site_save, self.site_reset])
        save_row.addWidget(self.site_save)
        save_row.addWidget(self.site_reset)
        save_row.addStretch()
        form.addRow(save_row)
        self.site_feedback = hint()
        form.addRow(self.site_feedback)
        layout.addWidget(group)
        layout.addWidget(hint("保存后影响该组的后续请求，服务器触发的 HTTP 429 冷却仍会保留。\n"
                              "域名归属和并发上限由内部插件配置声明，修改配置后重启生效。"))
        layout.addStretch()
        return page

    def _history_page(self):
        from empire.plugins.ui.records import RecordsPage

        self.history_tabs = QTabWidget()
        self.history_tabs.addTab(self._collection_history_page(), "采集记录")
        self.archive_records = RecordsPage(self.shell, "archives")
        self.error_records = RecordsPage(self.shell, "errors")
        self.history_tabs.addTab(self.archive_records, "归档记录")
        self.history_tabs.addTab(self.error_records, "错误记录")
        return self.history_tabs

    def _collection_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("采集项目"))
        self.history_task = QComboBox()
        self.history_task.addItem("全部项目", "")
        self.history_task.currentIndexChanged.connect(self.render_history)
        filters.addWidget(self.history_task)
        filters.addWidget(QLabel("运行结果"))
        self.history_filter = QComboBox()
        for label, status in [("全部结果", ""), ("已完成", "complete"), ("失败", "error"),
                              ("已暂停", "paused")]:
            self.history_filter.addItem(label, status)
        self.history_filter.currentIndexChanged.connect(self.render_history)
        filters.addWidget(self.history_filter)
        self.history_count = hint()
        filters.addStretch()
        filters.addWidget(self.history_count)
        layout.addLayout(filters)
        self.history = table(["任务", "开始时间 · 北京时间", "耗时", "结果", "采集条数", "触发方式"])
        self.history.itemSelectionChanged.connect(self.select_history)
        layout.addWidget(self.history, 1)
        self.history_empty = hint()
        layout.addWidget(self.history_empty)
        layout.addWidget(QLabel("运行详情"))
        self.history_detail = QTextEdit()
        self.history_detail.setReadOnly(True)
        self.history_detail.setMinimumHeight(140)
        self.history_detail.setMaximumHeight(210)
        self.history_detail.setPlaceholderText("选择一条记录，查看结束时间、批次信息及完整错误原因。")
        layout.addWidget(self.history_detail)
        return page

    def selected(self):
        if not self.data or not 0 <= self.jobs.currentRow() < len(self.data["jobs"]):
            return None
        return self.data["jobs"][self.jobs.currentRow()]

    def _policy(self):
        return {"enabled": self.enabled.isChecked(), "mode": self.mode.currentData(),
                "interval_minutes": self.interval.value(),
                "daily_time": self.daily.time().toString("HH:mm"),
                "request_retries": self.retries.value()}

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
        self.interval.setValue(policy["interval_minutes"])
        self.daily.setTime(QTime.fromString(policy["daily_time"], "HH:mm"))
        self.retries.setValue(policy["request_retries"])
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

    def select_site(self):
        if not self.data or not 0 <= self.sites.currentRow() < len(self.data["sites"]):
            return
        site = self.data["sites"][self.sites.currentRow()]
        self.site_baselines[site["name"]] = site["min_interval_ms"]
        if self.site_loaded != site["name"] or site["name"] not in self.site_drafts:
            changed = self.site_loaded != site["name"]
            self.site_loaded = site["name"]
            self._loading = True
            self.site_interval.setValue(self.site_drafts.get(site["name"], site["min_interval_ms"]))
            self._loading = False
            if changed:
                self.site_feedback.setText("有未保存修改" if site["name"] in self.site_drafts else "")
        domains = "、".join(f"{d} 及其子域名" for d in site["domains"])
        names = "、".join(j["name"] for j in self.data["jobs"] if j["rate_group"] == site["name"])
        self.site_scope.setText(f"当前网站组：{site['name']}\n共享范围：{domains}\n"
                                f"关联任务：{names or '尚无已注册任务'}")
        self._update_buttons()

    def site_edited(self):
        if self._loading or not self.site_loaded:
            return
        value = self.site_interval.value()
        saving = bool(self.action_context and self.action_context[0] == "configure_site"
                      and self.action_context[1][0] == self.site_loaded)
        if saving or value != self.site_baselines.get(self.site_loaded):
            self.site_drafts[self.site_loaded] = value
            self.site_feedback.setText("有未保存修改，当前请求仍使用已保存的间隔")
        else:
            self.site_drafts.pop(self.site_loaded, None)
            self.site_feedback.setText("与已保存设置一致")
        self._update_buttons()

    def reset_site(self):
        if self.site_loaded in self.site_baselines:
            self.site_drafts.pop(self.site_loaded, None)
            self._loading = True
            self.site_interval.setValue(self.site_baselines[self.site_loaded])
            self._loading = False
            self.site_feedback.setText("已撤销未保存修改")
            self._update_buttons()

    def submit(self, method, *args):
        if self.action:
            return
        target = self.site_feedback if method == "configure_site" else (
            self.task_feedback if method == "configure" else self.operation_feedback)
        try:
            self.action = self.shell.runtime.invoke("collection.control", method, *args)
            self.action_context = (method, deepcopy(args), target)
            target.setText("正在保存……" if method.startswith("configure") else "正在执行……")
        except Exception as exc:
            target.setText(redact(exc, self.shell.cfg))
        self._update_buttons()

    def execute(self, method, fresh):
        job = self.selected()
        if job:
            self.submit(method, job["id"], *(() if fresh is None else (fresh,)))

    def save_job(self):
        job = self.selected()
        if job:
            self.submit("configure", job["id"], self._policy())

    def save_site(self):
        if self.site_loaded:
            self.submit("configure_site", self.site_loaded, self.site_interval.value())

    def _finish_action(self):
        method, args, target = self.action_context
        try:
            result = self.action.result()
            text = result if isinstance(result, str) and len(result) != 32 else "任务已启动"
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
            elif method == "configure_site":
                name, interval = args
                self.site_baselines[name] = interval
                if self.data:
                    for site in self.data["sites"]:
                        if site["name"] == name:
                            site["min_interval_ms"] = interval
                current = self.site_interval.value() if self.site_loaded == name else self.site_drafts.get(name, interval)
                if current == interval:
                    self.site_drafts.pop(name, None)
                else:
                    self.site_drafts[name] = current
                if name in self.site_drafts:
                    text += "；之后的修改尚未保存"
            target.setText(text)
            # Ignore snapshots started before this change; they may contain old settings.
            self.query = None
        except Exception as exc:
            target.setText("操作失败：" + redact(exc, self.shell.cfg))
        self.action = self.action_context = None

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.timer.stop()
            return
        if self.action and self.action.done():
            self._finish_action()
        if self.query and self.query.done():
            try:
                self.data = self.query.result()
                self.render()
            except Exception as exc:
                self.summary.setText("采集管理服务未就绪：" + redact(exc, self.shell.cfg))
                self.data = None
            self.query = None
        self._update_buttons()
        if self.isVisible() and self.query is None:
            try:
                self.query = self.shell.runtime.invoke("collection.control", "snapshot")
            except Exception as exc:
                self.summary.setText(redact(exc, self.shell.cfg))

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
        self.site_save.setEnabled(bool(ready and self.site_loaded in self.site_drafts))
        self.site_reset.setEnabled(bool(ready and self.site_loaded in self.site_drafts))

    def _render_job_detail(self, job):
        self.task_name.setText(job["name"])
        self.fresh_button.setToolTip({
            "sina-news": "重新扫描最新窗口并建立增量基线，已有新闻保留；请先检查尚未处理的缺口。",
            "cninfo-calendar": "从 1990-12 起重新核验全部月份至下一年 12 月，已有日历保留；正常维护请用立即采集。",
        }.get(job["id"], "创建新批次，旧股票列表保留至新批次完整归档。"))
        self.detail.setText(f"{job['description']} · 网站频控组：{job['rate_group']}")
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

    def render(self):
        jobs = self.data["jobs"]
        running = sum(bool(j["active"]) for j in jobs)
        if self.section == "tasks":
            text = f"{len(jobs)} 个采集任务 · {running} 个执行中 · 时间均为北京时间"
        elif self.section == "sites":
            text = f"{len(self.data['sites'])} 个网站组 · 设置保存后立即作用于后续请求"
        else:
            text = "每项目：采集 100 条 · 归档 100 条 · 错误 300 条 · 仅存内存，Redis 重启后丢失"
        error = self.data.get("error")
        self.summary.setText(text + (" · " + redact(error, self.shell.cfg) if error else ""))
        selected = next((i for i, job in enumerate(jobs) if job["id"] == self.loaded_id), 0)
        self.jobs.blockSignals(True)
        values = []
        for job in jobs:
            policy = job["policy"]
            plan = {"manual": "仅手动", "interval": f"结束后 {policy['interval_minutes']} 分钟",
                    "daily": f"每天 {policy['daily_time']}"}[policy["mode"]]
            if not policy["enabled"]:
                plan = "已停用 · " + plan
            state = job["progress"].get("status", "running") if job["active"] else job["last_status"]
            values.append([job["name"], plan, STATUS.get(state, state), stamp(job["next_due"])])
        rows(self.jobs, values)
        self.jobs.setFixedHeight(min(174, max(88, self.jobs.horizontalHeader().height() + len(values) * 42 + 4)))
        if jobs:
            self.jobs.selectRow(selected)
        self.jobs.blockSignals(False)
        self.select_job()
        sites = self.data["sites"]
        site_index = next((i for i, site in enumerate(sites) if site["name"] == self.site_loaded), 0)
        self.sites.blockSignals(True)
        rows(self.sites, [[s["name"], ", ".join(f"*.{d}" for d in s["domains"]),
                          f"{s['min_interval_ms']:,} 毫秒", s["max_concurrency"]] for s in sites])
        if sites:
            self.sites.selectRow(site_index)
        self.sites.blockSignals(False)
        self.select_site()
        self.render_history()
        record_projects = {job["id"]: job for job in jobs}
        for record in self.data["history"]:
            record_projects.setdefault(record["task_id"], {"id": record["task_id"], "name": record["task_id"]})
        self.archive_records.set_projects(record_projects.values())
        self.error_records.set_projects(record_projects.values())
        self._update_buttons()

    def render_history(self):
        if not self.data:
            return
        names = {j["id"]: j["name"] for j in self.data["jobs"]}
        for record in self.data["history"]:
            names.setdefault(record["task_id"], record["task_id"])
        selected_task = self.history_task.currentData()
        options = [("全部项目", ""), *((name, ident) for ident, name in names.items())]
        if [self.history_task.itemData(i) for i in range(self.history_task.count())] != [value for _, value in options]:
            self.history_task.blockSignals(True)
            self.history_task.clear()
            for label, value in options:
                self.history_task.addItem(label, value)
            self.history_task.setCurrentIndex(max(0, self.history_task.findData(selected_task)))
            self.history_task.blockSignals(False)
        selected_key = self.history_selection
        status = self.history_filter.currentData()
        ident = self.history_task.currentData()
        project_records = [h for h in self.data["history"] if not ident or h["task_id"] == ident]
        self.history_records = [h for h in project_records if not status or h["status"] == status]
        self.history.blockSignals(True)
        values = []
        for record in self.history_records:
            count = record.get("result", {}).get("collected")
            values.append([names.get(record["task_id"], record["task_id"]), stamp(record["started_at"]),
                           elapsed(record["started_at"], record.get("finished_at")),
                           STATUS.get(record["status"], record["status"]),
                           f"{count:,}" if count is not None else "—",
                           "计划执行" if record.get("origin") == "schedule" else "手动执行"])
        rows(self.history, values)
        selected = next((i for i, item in enumerate(self.history_records)
                         if self._history_key(item) == selected_key), 0)
        if self.history_records:
            self.history.selectRow(selected)
        self.history.blockSignals(False)
        self.history_count.setText(f"显示 {len(self.history_records)} / {len(project_records)} 次运行 · 每项目最多 100 条")
        self.history_empty.setVisible(not self.history_records)
        self.history_empty.setText("该结果下暂无运行记录。" if status else
                                  "尚无运行记录。完成一次采集后，可以在这里查看结果和错误详情。")
        self.select_history()

    @staticmethod
    def _history_key(record):
        return record.get("run_id") or (record["task_id"], record["started_at"])

    def select_history(self):
        index = self.history.currentRow()
        if not 0 <= index < len(self.history_records):
            self.history_detail.clear()
            self.history_selection = None
            return
        record = self.history_records[index]
        self.history_selection = self._history_key(record)
        error = redact(record.get("error", ""), self.shell.cfg)
        result = record.get("result", {})
        lines = [f"结果：{STATUS.get(record['status'], record['status'])}    "
                 f"开始：{stamp(record['started_at'])}    结束：{stamp(record.get('finished_at'))}",
                 f"耗时：{elapsed(record['started_at'], record.get('finished_at'))}    "
                 f"运行编号：{record.get('run_id', '—')}"]
        if result.get("snapshot_id"):
            lines.append(f"数据批次：{result['snapshot_id']}")
        if error:
            lines.extend(["", "完整错误原因：", error])
        elif record["status"] == "paused":
            lines.extend(["", "已暂停并保留断点；启用任务并保存后，可以继续采集。"])
        elif record["status"] == "complete":
            lines.extend(["", "数据已通过完整性校验并归档，可在股票列表查看。"])
        detail = "\n".join(lines)
        if detail != self.history_detail.toPlainText():
            self.history_detail.setPlainText(detail)
