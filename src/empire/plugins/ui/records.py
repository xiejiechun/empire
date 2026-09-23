import json
from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from empire.core.config import redact
from empire.plugins.collection.control import CHINA

ARCHIVE_STATUS = {"complete": "已完成", "replayed": "已确认重放", "superseded": "已被新批次替代",
                  "invalid": "校验失败", "failed": "归档失败"}


def record_time(value):
    if not value:
        return "—"
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, CHINA).strftime("%m-%d %H:%M:%S")
    try:
        return datetime.fromisoformat(value).astimezone(CHINA).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


class RecordsPage(QWidget):
    """Bounded Redis histories; this page never sends records to MySQL."""

    def __init__(self, shell, kind):
        super().__init__()
        from empire.plugins.ui.collection import hint, table

        self.shell, self.kind = shell, kind
        self.records = []
        self.query = self.query_spec = self.clear_action = None
        self.selection = set()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("采集项目"))
        self.project = QComboBox()
        self.project.currentIndexChanged.connect(self.project_changed)
        filters.addWidget(self.project, 1)
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.reload)
        filters.addWidget(self.refresh)
        layout.addLayout(filters)
        description = ("每个项目最近 300 条错误，仅存 Redis。原文样本最多 64 KiB，超过部分仅保留长度与摘要。"
                       if kind == "errors" else "每个项目最近 100 条归档记录，仅存 Redis；与采集运行记录分别保留。")
        layout.addWidget(hint(description))
        self.table = table(["发生时间 · 北京时间", "阶段", "错误原因", "HTTP 状态"] if kind == "errors"
                           else ["归档时间 · 北京时间", "结果", "入库条数", "批次标识"])
        if kind == "errors":
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        else:
            for column in (0, 1, 2):
                self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.table.currentCellChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        self.status = hint("请选择采集项目")
        layout.addWidget(self.status)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(160)
        self.detail.setMaximumHeight(260)
        self.detail.setPlaceholderText("选择记录查看详情；Ctrl / Shift 可选择多条错误记录。" if kind == "errors"
                                       else "选择记录查看归档批次和结果。")
        layout.addWidget(self.detail)
        self.verified = QCheckBox("所选错误对应的问题已修复，并且已完成验证")
        self.clear_button = QPushButton("清除已修复记录")
        self.clear_button.clicked.connect(self.clear_selected)
        self.verified.toggled.connect(self.update_actions)
        if kind == "errors":
            layout.addWidget(self.verified)
            actions = QHBoxLayout()
            actions.addWidget(self.clear_button)
            actions.addStretch()
            layout.addLayout(actions)
            layout.addWidget(hint("清除仅针对当前选中的记录，不会清空项目或删除之后产生的新错误。查看记录、采集成功都不会自动清除。"))
        else:
            self.verified.hide()
            self.clear_button.hide()
        self.feedback = hint()
        layout.addWidget(self.feedback)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1500)
        self.update_actions()

    def set_projects(self, values):
        options = {value["id"]: value["name"] for value in values}
        if self.kind == "errors":
            options.setdefault("unknown", "未识别项目")
        if list(options) == [self.project.itemData(i) for i in range(self.project.count())]:
            return
        selected = self.project.currentData()
        self.project.blockSignals(True)
        self.project.clear()
        for ident, name in options.items():
            self.project.addItem(name, ident)
        self.project.setCurrentIndex(max(0, self.project.findData(selected)))
        self.project.blockSignals(False)
        if self.project.currentData() != selected:
            self.project_changed()

    def project_changed(self):
        self.records = []
        self.selection = set()
        self.query = self.query_spec = None
        self.verified.setChecked(False)
        self.feedback.clear()
        self.render()
        if self.isVisible():
            self.reload()

    def reload(self):
        if getattr(self.shell, "shutting_down", False) or self.query or not self.project.currentData():
            return
        try:
            ident = self.project.currentData()
            self.query = self.shell.runtime.invoke("collection.records", f"list_{self.kind}", ident)
            self.query_spec = ident
            if not self.records:
                self.status.setText("正在读取记录……")
        except Exception as exc:
            self.status.setText("记录服务未就绪：" + redact(exc, self.shell.cfg))

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.timer.stop()
            return
        if self.clear_action:
            future, project_id, record_ids = self.clear_action
            if future.done():
                try:
                    result = future.result()
                    count = result
                    index = self.project.findData(project_id)
                    name = self.project.itemText(index) if index >= 0 else project_id
                    self.feedback.setText(f"{name}：已清除 {count} 条选中记录；新产生的错误继续保留。")
                    if project_id == self.project.currentData():
                        self.records = [r for r in self.records if r["id"] not in record_ids]
                        self.selection.difference_update(record_ids)
                        self.query = self.query_spec = None
                        self.render()
                except Exception as exc:
                    self.feedback.setText("清除失败：" + redact(exc, self.shell.cfg))
                self.clear_action = None
                self.verified.setChecked(False)
                self.update_actions()
        if self.query and self.query.done():
            future, project = self.query, self.query_spec
            self.query = self.query_spec = None
            if project == self.project.currentData():
                try:
                    self.records = future.result()
                    self.render()
                except Exception as exc:
                    self.status.setText("读取失败：" + redact(exc, self.shell.cfg))
        if self.isVisible():
            self.reload()

    def render(self):
        from empire.plugins.ui.collection import rows

        selected_ids = self.selected_ids() if self.table.rowCount() else self.selection
        current = self.table.currentRow()
        current_id = self.table.item(current, 0).data(Qt.ItemDataRole.UserRole) if current >= 0 and self.table.item(current, 0) else None
        self.table.blockSignals(True)
        if self.kind == "errors":
            values = [[record_time(r.get("created_at")), r.get("stage", "—"),
                       redact(r.get("error", ""), self.shell.cfg), r.get("status_code") or "—"]
                      for r in self.records]
        else:
            values = [[record_time(r.get("created_at")), ARCHIVE_STATUS.get(r.get("status"), r.get("status", "—")),
                       r.get("row_count", "—"), r.get("snapshot_id", "—")] for r in self.records]
        rows(self.table, values)
        self.table.clearSelection()
        selection_model = self.table.selectionModel()
        for index, record in enumerate(self.records):
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, record["id"])
            if record["id"] in selected_ids:
                selection_model.select(self.table.model().index(index, 0),
                                       QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            if record["id"] == current_id:
                selection_model.setCurrentIndex(self.table.model().index(index, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
        self.table.blockSignals(False)
        self.status.setText(f"{len(self.records)} 条记录 · 时间为北京时间" if self.records else "当前项目暂无记录")
        self.show_detail()

    def selected_ids(self):
        return {self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.table.selectionModel().selectedRows() if self.table.item(index.row(), 0)}

    def show_detail(self):
        selected = self.selected_ids()
        if selected != self.selection:
            self.verified.setChecked(False)
        self.selection = selected
        index = self.table.currentRow()
        record = self.records[index] if 0 <= index < len(self.records) and self.records[index]["id"] in selected else None
        if not record:
            self.detail.clear()
        else:
            lines = [f"记录：{record['id']}    项目：{record.get('project_id', '—')}",
                     f"时间：{record_time(record.get('created_at'))}    应用版本：{record.get('version', '—')}"]
            if self.kind == "errors":
                lines.extend([f"阶段：{record.get('stage', '—')}    HTTP 状态：{record.get('status_code') or '—'}",
                              f"请求地址：{record.get('request_url') or '—'}", f"错误：{record.get('error', '')}",
                              "元数据：" + json.dumps(record.get("metadata", {}), ensure_ascii=False, indent=2),
                              f"原文长度：{record.get('original_bytes', 0)} 字节    样本截断：{'是' if record.get('body_truncated') else '否'}",
                              f"原文 SHA-256：{record.get('original_sha256') or '—'}",
                              "", "错误原文样本（已脱敏，最多 64 KiB）：", record.get("body") or "无原文样本"])
            else:
                lines.extend([f"状态：{ARCHIVE_STATUS.get(record.get('status'), record.get('status', '—'))}",
                              f"开始：{record_time(record.get('started_at'))}    结束：{record_time(record.get('finished_at'))}（北京时间）",
                              f"入库条数：{record.get('row_count', '—')}",
                              f"数据批次：{record.get('snapshot_id', '—')}",
                              "失败原因：" + (record.get("error") or "无")])
            text = redact("\n".join(lines), self.shell.cfg)
            if text != self.detail.toPlainText():
                self.detail.setPlainText(text)
        self.update_actions()

    def update_actions(self):
        self.clear_button.setEnabled(bool(self.kind == "errors" and self.selection
                                          and self.verified.isChecked() and not self.clear_action
                                          and not getattr(self.shell, "shutting_down", False)))

    def clear_selected(self):
        ids = sorted(self.selected_ids())
        if not ids or not self.verified.isChecked() or self.clear_action or getattr(self.shell, "shutting_down", False):
            return
        ident = self.project.currentData()
        try:
            future = self.shell.runtime.invoke("collection.records", "clear_errors", ident, ids)
            self.clear_action = (future, ident, tuple(ids))
            self.feedback.setText(f"正在清除所选 {len(ids)} 条已修复记录……")
        except Exception as exc:
            self.feedback.setText("清除失败：" + redact(exc, self.shell.cfg))
        self.update_actions()
