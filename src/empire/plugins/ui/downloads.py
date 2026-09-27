"""Independent management page for durable, restart-applied download resource settings."""
from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.download_settings import FIELDS, validate_settings
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.core.redaction import redact
from empire.desktop.theme import PAGE_SPACING
from empire.plugins.ui.common import hint
from empire.plugins.ui.download_fields import DownloadFields
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class DownloadSettingsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.query_scope = QueryScope(self)
        self.query = self.action = self.submitted = None
        self.saved = self.active = None
        self.pending_restart = False
        self.next_query = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(PAGE_SPACING)
        self.title = QLabel("下载资源")
        self.title.setObjectName("pageTitle")
        layout.addWidget(self.title)
        layout.addWidget(hint("设置单响应大小、跨任务共享缓冲与文件磁盘预算。"
                              "保存到 MySQL，重启电脑后保留；重启软件后生效。"))
        self.summary = hint("正在读取下载资源设置……")
        layout.addWidget(self.summary)
        self.fields = DownloadFields()
        self.fields.changed.connect(self.edited)
        self.fields.recommendation_applied.connect(self.recommended)
        self.fields.setEnabled(False)
        self.editor = QScrollArea()
        self.editor.setWidgetResizable(True)
        self.editor.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor.setWidget(self.fields)
        layout.addWidget(self.editor, 1)
        self.validation = hint()
        layout.addWidget(self.validation)
        self.feedback = hint()
        layout.addWidget(self.feedback)
        self.save_bar = QWidget()
        buttons = QHBoxLayout(self.save_bar)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        self.reset_button = QPushButton("撤销修改")
        self.reset_button.clicked.connect(self.reset)
        self.defaults_button = QPushButton("恢复默认")
        self.defaults_button.setToolTip("仅修改草稿，点击保存设置后才会保存")
        self.defaults_button.clicked.connect(self.restore_defaults)
        for button in (self.save_button, self.reset_button, self.defaults_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addWidget(self.save_bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        self.update_controls()

    @property
    def dirty(self):
        return self.saved is not None and self.fields.values() != self.saved

    def apply_snapshot(self, data, *, preserve_draft=None):
        if preserve_draft is None:
            preserve_draft = self.dirty or self.action is not None
        self.saved = dict(data["saved"])
        self.active = dict(data["active"]) if data["active"] is not None else None
        self.pending_restart = data["pending_restart"]
        if not preserve_draft:
            self.fields.load(self.saved)
        self.fields.setEnabled(True)
        self.fields.show_state(self.saved, self.active)
        if self.active is None:
            self.summary.setText("HTTP 服务未启动 · 当前没有生效值，设置仍可保存")
        elif self.pending_restart:
            self.summary.setText("已保存设置与当前运行值不同 · 重启软件后生效，进行中的下载不受影响")
        else:
            self.summary.setText("已保存设置正在生效 · 编辑草稿不会改变当前下载")
        self.update_controls()

    def edited(self):
        self.feedback.setText("有未保存修改" if self.dirty else "与已保存设置一致")
        self.update_controls()

    def recommended(self, count):
        text = (f"已填入 {count:,} 台推荐值；尚未保存，点击保存设置并重启软件后生效" if self.dirty
                else f"当前草稿与已保存的 {count:,} 台推荐值一致，无须重复保存")
        self.feedback.setText(text)

    def reset(self):
        if self.saved is not None and self.action is None:
            self.fields.load(self.saved)
            self.feedback.setText("已撤销未保存修改")
            self.update_controls()

    def restore_defaults(self):
        if self.saved is not None and self.action is None:
            self.fields.load({field.key: field.default for field in FIELDS})
            self.feedback.setText("默认值已填入草稿，点击保存设置后才会保存")
            self.update_controls()

    def update_controls(self):
        error = ""
        if self.saved is not None:
            try:
                validate_settings(self.fields.values())
            except ValueError as exc:
                error = redact(exc, self.shell.cfg)
        self.validation.setText(error)
        self.validation.setVisible(bool(error))
        idle = self.saved is not None and self.action is None
        self.save_button.setEnabled(bool(idle and self.dirty and not error))
        self.reset_button.setEnabled(bool(idle and self.dirty))
        self.defaults_button.setEnabled(idle)

    def save(self):
        if self.action is not None or self.saved is None:
            return
        try:
            values = validate_settings(self.fields.values())
            self.action = self.shell.runtime.invoke("download.settings", "save", values)
            self.submitted = dict(values)
            self.feedback.setText("正在保存；可以继续编辑，后续修改不会包含在本次保存中")
        except Exception as exc:
            self.feedback.setText("保存失败：" + redact(exc, self.shell.cfg))
        self.update_controls()

    def finish_save(self):
        try:
            data = self.action.result()
            later_edits = self.fields.values() != self.submitted
            self.apply_snapshot(data, preserve_draft=later_edits)
            text = "设置已保存，重启软件后生效" if data["pending_restart"] else "设置已保存"
            self.feedback.setText(text + ("；之后的修改尚未保存" if self.dirty else ""))
        except Exception as exc:
            self.feedback.setText("保存失败：" + redact(exc, self.shell.cfg))
        # A read started before the write may contain the previous saved values.
        if self.query is not None:
            self.query_scope.cancel("download-settings")
        self.query = self.action = self.submitted = None
        self.next_query = 0
        self.update_controls()

    def query_failed(self, exc):
        text = self.query_scope.failure_message(
            "download-settings", "设置读取失败", redact(exc, self.shell.cfg),
            stale=self.saved is not None,
        )
        if self.saved is not None:
            self.fields.show_state(self.saved, self.active, stale=True)
            text += "；未保存草稿已保留"
        self.summary.setText(text)

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.action is not None and self.action.done():
            self.finish_save()
        if self.query is not None and self.query.done():
            try:
                self.apply_snapshot(self.query_scope.result("download-settings", self.query))
            except Exception as exc:
                self.query_failed(exc)
            self.query = None
        if self.isVisible() and self.action is None and self.query is None and monotonic() >= self.next_query:
            self.next_query = monotonic() + 3
            self.query = self.query_scope.invoke(
                "download-settings", self.shell.runtime,
                "download.settings", "snapshot")


class DownloadSettingsUiPlugin(UiPlugin):
    manifest = PluginManifest("ui.downloads", "下载资源界面", provides=("ui.pages.downloads",),
                              autostart=True, description="管理单响应、共享缓冲和文件下载资源预算")

    def create_pages(self):
        return (PageContribution("downloads", "下载资源", DownloadSettingsPage, "采集管理", 4,
                                 "管理下载大小、内存缓冲和磁盘配额"),)
