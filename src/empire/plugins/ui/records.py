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

from empire.core.redaction import redact
from empire.plugins.ui.record_detail import ARCHIVE_STATUS, record_detail, record_time


class RecordsPage(QWidget):
    """Bounded Redis histories; this page never sends records to MySQL."""

    def __init__(self, shell, kind):
        super().__init__()
        from empire.plugins.ui.common import accessible, hint, table

        self.shell, self.kind = shell, kind
        from empire.plugins.ui.queries import QueryScope
        self.query_scope = QueryScope(self)
        self.records = []
        self.query = self.query_spec = self.clear_action = None
        self.detail_query = self.detail_spec = self.detail_record = self.detail_id = None
        self.offset = self.total = 0
        self.revision = None
        self.selection = set()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("采集项目"))
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.project.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        accessible(self.project, "选择采集项目")
        self.project.currentIndexChanged.connect(self.project_changed)
        filters.addWidget(self.project, 1)
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(lambda: self.reload(True))
        filters.addWidget(self.refresh)
        layout.addLayout(filters)
        description = ("每个项目最近 300 条错误，仅存 Redis。样本最多 64 KiB；未完整下载时，仅记录已读长度与样本摘要。"
                       if kind == "errors" else "每个项目最近 100 条归档记录，仅存 Redis；已处理包含确认无需写入，业务写入才表示数据发生变化。")
        layout.addWidget(hint(description))
        self.table = table(["发生时间 · 北京时间", "阶段", "错误原因", "HTTP 状态"] if kind == "errors"
                           else ["归档时间 · 北京时间", "结果", "已处理记录", "业务写入记录", "批次标识"])
        if kind == "errors":
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        else:
            for column in (0, 1, 2, 3):
                self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.table.currentCellChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        self.navigation = QHBoxLayout()
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.clicked.connect(lambda: self.move(-50))
        self.next.clicked.connect(lambda: self.move(50))
        self.navigation.addWidget(self.previous)
        self.navigation.addWidget(self.next)
        self.navigation.addStretch()
        layout.addLayout(self.navigation)
        if kind != "errors":
            self.previous.hide()
            self.next.hide()
        self.status = hint("请选择采集项目")
        self.status.setAccessibleName("运行记录读取状态")
        layout.addWidget(self.status)
        self.detail = QTextEdit()
        accessible(self.detail, "运行记录详情")
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
        self.query_scope.cancel("records")
        self.query_scope.cancel("record-detail")
        self.records = []
        self.selection = set()
        self.query = self.query_spec = None
        self.detail_query = self.detail_spec = self.detail_record = self.detail_id = None
        self.offset = self.total = 0
        self.revision = None
        self.verified.setChecked(False)
        self.feedback.clear()
        self.render()
        if self.isVisible():
            self.reload()

    def reload(self, force=False):
        if getattr(self.shell, "shutting_down", False) or self.query or not self.project.currentData():
            return
        try:
            ident = self.project.currentData()
            if self.kind == "errors":
                if force:
                    self.revision = None
                self.query = self.query_scope.invoke(
                    "records", self.shell.runtime, "collection.records",
                    "list_error_summaries", ident, self.offset, 50, self.revision)
                self.query_spec = (ident, self.offset)
            else:
                self.query = self.query_scope.invoke(
                    "records", self.shell.runtime,
                    "collection.records", "list_archives", ident)
                self.query_spec = (ident, 0)
            if not self.records:
                self.status.setText("正在读取记录……")
        except Exception as exc:
            self.status.setText("记录服务未就绪：" + redact(exc, self.shell.cfg))

    def move(self, step):
        target = max(0, self.offset + step)
        if target == self.offset or target >= self.total:
            return
        self.offset, self.revision = target, None
        self.selection.clear()
        self.detail_record = self.detail_id = None
        self.reload()

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
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
                        self.total = max(0, self.total - count)
                        self.revision = None
                        self.selection.difference_update(record_ids)
                        self.detail_record = self.detail_id = None
                        self.query = self.query_spec = None
                        self.render()
                except Exception as exc:
                    self.feedback.setText("清除失败：" + redact(exc, self.shell.cfg))
                self.clear_action = None
                self.verified.setChecked(False)
                self.update_actions()
        if self.query and self.query.done():
            future, spec = self.query, self.query_spec
            self.query = self.query_spec = None
            if spec == (self.project.currentData(), self.offset):
                try:
                    result = self.query_scope.result("records", future)
                    if self.kind == "errors":
                        self.revision = result["revision"]
                        self.total = result["total"]
                        if result["changed"]:
                            self.offset = result["offset"]
                            self.records = result["rows"]
                            self.detail_record = self.detail_id = None
                            self.render()
                    else:
                        self.records = result
                        self.total = len(result)
                        self.render()
                except Exception as exc:
                    self.status.setText(self.query_scope.failure_message(
                        "records", "读取失败", redact(exc, self.shell.cfg),
                        stale=bool(self.records),
                    ))
            else:
                self.query_scope.discard("records", future)
        if self.detail_query and self.detail_query.done():
            future, spec = self.detail_query, self.detail_spec
            self.detail_query = self.detail_spec = None
            if (spec[0] == self.project.currentData() and spec[1] in self.selected_ids()
                    and spec[2] == self.revision):
                try:
                    self.detail_id = spec[1]
                    self.detail_record = self.query_scope.result("record-detail", future)
                    self.show_detail()
                except Exception as exc:
                    self.detail.clear()
                    self.detail.setPlaceholderText("读取详情失败：" + redact(exc, self.shell.cfg))
            elif self.selected_ids():
                self.query_scope.discard("record-detail", future)
                self.show_detail()
            else:
                self.query_scope.discard("record-detail", future)
        if self.isVisible():
            self.reload()

    def render(self):
        from empire.plugins.ui.common import rows

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
                       r.get("processed_count", "—"), r.get("written_count", "—"),
                       r.get("snapshot_id", "—")] for r in self.records]
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
        if self.kind == "errors":
            self.previous.setEnabled(self.offset > 0)
            self.next.setEnabled(self.offset + len(self.records) < self.total)
            self.status.setText((f"共 {self.total} 条 · 第 {self.offset // 50 + 1} 页 · 时间为北京时间"
                                 if self.total else "当前项目暂无记录"))
        else:
            self.status.setText(f"{len(self.records)} 条记录 · 时间为北京时间" if self.records else "当前项目暂无记录")
        self.show_detail()

    def selected_ids(self):
        return {self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.table.selectionModel().selectedRows() if self.table.item(index.row(), 0)}

    def show_detail(self):
        selected = self.selected_ids()
        if selected != self.selection:
            self.verified.setChecked(False)
            if self.detail_query is not None:
                self.query_scope.cancel("record-detail")
                self.detail_query = self.detail_spec = None
        self.selection = selected
        index = self.table.currentRow()
        record = self.records[index] if 0 <= index < len(self.records) and self.records[index]["id"] in selected else None
        if self.kind == "errors" and record:
            if self.detail_id != record["id"]:
                if not self.detail_query:
                    try:
                        ident = self.project.currentData()
                        self.detail_query = self.query_scope.invoke(
                            "record-detail", self.shell.runtime, "collection.records",
                            "get_error", ident, record["id"])
                        self.detail_spec = (ident, record["id"], self.revision)
                    except Exception as exc:
                        self.detail.setPlaceholderText("读取详情失败：" + redact(exc, self.shell.cfg))
                self.detail.clear()
                self.detail.setPlaceholderText("正在读取错误详情……")
                self.update_actions()
                return
            record = self.detail_record
        if not record:
            self.detail.clear()
        else:
            text = record_detail(record, self.kind, self.shell.cfg)
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
