
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from empire.desktop.theme import PAGE_SPACING
from empire.plugins.ui.common import Pager, accessible, bind_find, hint

from .task_menu import TaskMenu
from .task_runtime import build_runtime


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
        self.task_filter_widgets = (self.task_search, self.task_source, self.task_category, self.task_status)
        for combo in self.task_filter_widgets[1:]:
            combo.currentIndexChanged.connect(self.filters_changed)
        self.task_search.textChanged.connect(self.filters_changed)
        layout.addWidget(filters_widget)
        self._arrange_task_filters(False)
        self.focus_panel = QWidget()
        focus_row = QHBoxLayout(self.focus_panel)
        focus_row.setContentsMargins(0, 0, 0, 0)
        self.focus_notice = hint()
        self.focus_notice.setAccessibleName("采集任务定位状态")
        self.clear_focus_button = QPushButton("返回原筛选")
        self.clear_focus_button.clicked.connect(self.clear_navigation_focus)
        self.focus_notice.hide()
        self.clear_focus_button.hide()
        focus_row.addWidget(self.focus_notice, 1)
        focus_row.addWidget(self.clear_focus_button)
        self.focus_panel.hide()
        layout.addWidget(self.focus_panel)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.task_split = split
        listing = QWidget()
        list_layout = QVBoxLayout(listing)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_menu = TaskMenu()
        self.task_menu.itemSelectionChanged.connect(self.select_job)
        list_layout.addWidget(self.task_menu, 1)
        self.task_pager = Pager(compact=True)
        self.task_pager.changed.connect(self.change_page)
        list_layout.addWidget(self.task_pager)
        self.task_empty = hint("没有匹配的任务，请调整搜索或筛选条件。")
        self.task_empty.hide()
        list_layout.addWidget(self.task_empty)
        split.addWidget(listing)
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self.task_name = QLabel("请选择采集任务")
        self.task_name.setWordWrap(True)
        self.task_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.task_name.setTextFormat(Qt.TextFormat.PlainText)
        self.task_name.setObjectName("sectionTitle")
        self.detail = hint()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        runtime_group = build_runtime(self)
        actions = QGridLayout()
        self.run_button = QPushButton("立即采集")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(lambda: self.execute("run", False))
        self.fresh_button = QPushButton("重新采集")
        self.fresh_button.setToolTip("重新开始采集；不会删除已归档业务数据。")
        self.fresh_button.clicked.connect(lambda: self.execute("run", True))
        self.pause_button = QPushButton("暂停任务")
        self.pause_button.setToolTip("暂停当前采集并关闭后续计划，保留断点。恢复前需启用任务并保存。")
        self.pause_button.clicked.connect(lambda: self.execute("pause", None))
        self.run_buttons = [self.run_button, self.fresh_button]
        self.buttons.extend([*self.run_buttons, self.pause_button])
        actions.addWidget(self.run_button, 0, 0)
        actions.addWidget(self.pause_button, 0, 1)
        actions.addWidget(self.fresh_button, 0, 2)
        actions.setColumnStretch(3, 1)
        self.operation_feedback = hint("采集操作使用已保存的设置；暂停后保留断点。")
        group = QGroupBox("执行计划")
        self.job_form = QFormLayout(group)
        self.job_form.setVerticalSpacing(10)
        self.job_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.job_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.enabled = QCheckBox("启用任务，允许手动与计划执行")
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
        self.route_mode.addItem("代理优先，可回退直连", "proxy_fallback")
        self.route_mode.addItem("仅使用代理", "proxy_only")
        for combo in (self.mode, self.route_mode):
            combo.setMinimumContentsLength(12)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.route_mode.setCurrentIndex(self.route_mode.findData('proxy_fallback'))
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
        self.task_inspector.setMinimumSize(0, 140)
        inspector_panel = QWidget()
        inspector_layout = QVBoxLayout(inspector_panel)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(8)
        inspector_layout.addWidget(self.task_name)
        inspector_layout.addWidget(self.detail)
        inspector_layout.addLayout(actions)
        inspector_layout.addWidget(self.operation_feedback)
        inspector_layout.addWidget(self.task_inspector, 1)
        self.save_panel = QWidget()
        save_panel_layout = QHBoxLayout(self.save_panel)
        save_panel_layout.setContentsMargins(0, 0, 0, 0)
        save_panel_layout.addWidget(self.task_feedback, 1)
        save_panel_layout.addLayout(save_row)
        inspector_layout.addWidget(self.save_panel)
        self.task_inspector.currentChanged.connect(lambda index: self.save_panel.setVisible(index == 1))
        self.save_panel.hide()
        self.detail_stack = QStackedWidget()
        empty = QLabel("请选择具体任务\n展开左侧数据来源，查看运行详情或设置执行计划。")
        empty.setWordWrap(True)
        empty.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setObjectName('muted')
        self.detail_stack.addWidget(empty)
        self.detail_stack.addWidget(inspector_panel)
        split.addWidget(self.detail_stack)
        split.setChildrenCollapsible(False)
        split.setSizes([320, 700])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.detail_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.operation_feedback.setToolTip('采集操作使用已保存的设置；暂停任务会关闭后续计划并保留断点。')
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

