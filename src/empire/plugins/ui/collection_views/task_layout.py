
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from empire.desktop.theme import PAGE_SPACING
from empire.plugins.ui.common import Pager, accessible, bind_find, hint, table


class TaskLayout:
    """Task list and schedule editor layout; behavior belongs to TasksPage."""
    def _tasks_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(PAGE_SPACING)
        filters_widget = QWidget()
        filters = QGridLayout(filters_widget)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(PAGE_SPACING)
        filters.setVerticalSpacing(8)
        self.task_filters = filters
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText("搜索任务名称、ID、来源")
        self.task_search.setClearButtonEnabled(True)
        self.task_search.setMaxLength(100)
        accessible(self.task_search, "搜索采集任务", "输入任务名称、ID 或来源；按 Ctrl+F 可回到此处。")
        bind_find(page, self.task_search)
        self.task_category, self.task_source, self.task_status = QComboBox(), QComboBox(), QComboBox()
        self.task_category.addItem("全部分类", "")
        self.task_source.addItem("全部来源", "")
        accessible(self.task_category, "按任务分类筛选")
        accessible(self.task_source, "按任务来源筛选")
        accessible(self.task_status, "按任务状态筛选")
        for label, value in (("全部状态", ""), ("执行中", "running"), ("失败", "error"),
                             ("已停用", "disabled"), ("已完成", "complete"), ("待执行", "idle"), ("已暂停", "paused")):
            self.task_status.addItem(label, value)
        self.task_filter_widgets = (self.task_search, self.task_category, self.task_source, self.task_status)
        for combo in self.task_filter_widgets[1:]:
            combo.currentIndexChanged.connect(self.filters_changed)
        self.task_search.textChanged.connect(self.filters_changed)
        layout.addWidget(filters_widget)
        self._arrange_task_filters(False)
        focus_row = QHBoxLayout()
        self.focus_notice = hint()
        self.focus_notice.setAccessibleName("采集任务定位状态")
        self.clear_focus_button = QPushButton("返回原筛选")
        self.clear_focus_button.clicked.connect(self.clear_navigation_focus)
        self.focus_notice.hide()
        self.clear_focus_button.hide()
        focus_row.addWidget(self.focus_notice, 1)
        focus_row.addWidget(self.clear_focus_button)
        layout.addLayout(focus_row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.task_split = split
        listing = QWidget()
        list_layout = QVBoxLayout(listing)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.jobs = table(["采集任务", "来源 / 分类", "执行计划", "状态", "下次执行"])
        self.jobs.setAccessibleName("采集任务列表")
        self.jobs.setMinimumHeight(180)
        self.jobs.itemSelectionChanged.connect(self.select_job)
        list_layout.addWidget(self.jobs, 1)
        self.task_pager = Pager()
        self.task_pager.changed.connect(self.change_page)
        list_layout.addWidget(self.task_pager)
        self.task_empty = hint("没有匹配的任务，请调整搜索或筛选条件。")
        self.task_empty.hide()
        list_layout.addWidget(self.task_empty)
        split.addWidget(listing)
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        group = QGroupBox("任务详情")
        box = QVBoxLayout(group)
        self.task_name = QLabel("请选择采集任务")
        self.task_name.setObjectName("sectionTitle")
        box.addWidget(self.task_name)
        self.detail = hint()
        box.addWidget(self.detail)
        self.progress_label = QLabel("等待任务状态")
        self.progress_label.setWordWrap(True)
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
        for button in [self.run_button, self.pause_button]:
            actions.addWidget(button)
        actions.addStretch()
        box.addWidget(self.fresh_button)
        self.operation_feedback = hint("采集操作使用已保存的设置；暂停后保留断点。")
        box.addWidget(self.operation_feedback)
        runtime_group = group
        group = QGroupBox("执行计划")
        self.job_form = QFormLayout(group)
        self.job_form.setVerticalSpacing(12)
        self.job_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.enabled = QCheckBox("启用任务，允许手动采集和计划执行")
        self.mode = QComboBox()
        accessible(self.mode, "执行方式")
        for label, value in [("仅手动执行", "manual"), ("固定间隔", "interval"), ("每天定时", "daily")]:
            self.mode.addItem(label, value)
        self.interval = QSpinBox()
        accessible(self.interval, "每次结束后等待秒数")
        self.interval.setRange(1, 2592000)
        self.interval.setSuffix(" 秒")
        self.daily = QTimeEdit()
        accessible(self.daily, "每日执行时间，北京时间")
        self.daily.setDisplayFormat("HH:mm")
        self.retries = QSpinBox()
        accessible(self.retries, "单次请求失败重试次数")
        self.retries.setRange(0, 5)
        self.retries.setSuffix(" 次")
        self.job_form.addRow(self.enabled)
        self.job_form.addRow("执行方式", self.mode)
        self.job_form.addRow("每次结束后等待", self.interval)
        self.job_form.addRow("每日时间 · 北京时间", self.daily)
        self.job_form.addRow("单次请求失败重试", self.retries)
        self.route_mode = QComboBox()
        accessible(self.route_mode, "网络方式")
        self.route_mode.addItem("本机直连", "direct")
        self.route_mode.addItem("代理优先，暂不可用时自动直连", "proxy_fallback")
        self.route_mode.addItem("仅使用代理", "proxy_only")
        self.route_mode.currentIndexChanged.connect(self.job_edited)
        self.job_form.addRow("网络方式", self.route_mode)
        self.job_form.addRow(hint("网络方式在下一轮采集生效。代理设备上下线自动同步；自动直连仍遵守站点访问规则。"))
        self.plan_note = hint()
        self.job_form.addRow(self.plan_note)
        save_row = QHBoxLayout()
        self.save_button = QPushButton("保存执行计划")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save_job)
        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, page)
        save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save_shortcut.activated.connect(self.save_button.click)
        page._save_shortcut = save_shortcut
        self.reset_button = QPushButton("撤销修改")
        self.reset_button.clicked.connect(self.reset_job)
        self.buttons.extend([self.save_button, self.reset_button])
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.reset_button)
        save_row.addStretch()
        self.task_feedback = hint()
        self.task_feedback.setAccessibleName("执行计划保存状态")
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode.currentIndexChanged.connect(self.job_edited)
        self.enabled.toggled.connect(self.job_edited)
        self.interval.valueChanged.connect(self.job_edited)
        self.daily.timeChanged.connect(self.job_edited)
        self.retries.valueChanged.connect(self.job_edited)
        detail_layout.addWidget(group)
        detail_layout.addWidget(hint("配置保存到 MySQL，重启后保留。编辑草稿按任务保留，切换任务不会丢失。"))
        detail_layout.addStretch()
        self.task_inspector = QTabWidget()
        for title, content in (("运行详情", runtime_group), ("任务配置", detail_page)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(content)
            self.task_inspector.addTab(scroll, title)
        self.task_inspector.setMinimumWidth(320)
        inspector_panel = QWidget()
        inspector_layout = QVBoxLayout(inspector_panel)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.addLayout(actions)
        inspector_layout.addWidget(self.task_inspector, 1)
        inspector_layout.addWidget(self.task_feedback)
        inspector_layout.addLayout(save_row)
        split.addWidget(inspector_panel)
        split.setChildrenCollapsible(False)
        split.setSizes([650, 370])
        split.setStretchFactor(0, 1)
        layout.addWidget(split, 1)
        self.mode_changed()
        return page

    def _arrange_task_filters(self, narrow):
        for widget in self.task_filter_widgets:
            self.task_filters.removeWidget(widget)
        if narrow:
            self.task_filters.addWidget(self.task_search, 0, 0, 1, 3)
            for column, combo in enumerate(self.task_filter_widgets[1:]):
                self.task_filters.addWidget(combo, 1, column)
        else:
            for column, widget in enumerate(self.task_filter_widgets):
                self.task_filters.addWidget(widget, 0, column)
        self.task_filters.setColumnStretch(0, 1)

