
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from empire.core.redaction import redact
from empire.plugins.ui.common import STATUS, Pager, accessible, elapsed, hint, rows, stamp, table

from .base import CollectionView


class HistoryPage(CollectionView):
    section = "history"
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
        self.history_task.setEditable(True)
        self.history_task.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.history_task.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.history_task.addItem("全部项目", "")
        accessible(self.history_task, "按采集项目筛选运行记录")
        self.history_task.currentIndexChanged.connect(self.history_filters_changed)
        filters.addWidget(self.history_task)
        filters.addWidget(QLabel("运行结果"))
        self.history_filter = QComboBox()
        accessible(self.history_filter, "按运行结果筛选采集记录")
        for label, status in [("全部结果", ""), ("已完成", "complete"), ("失败", "error"),
                              ("已暂停", "paused")]:
            self.history_filter.addItem(label, status)
        self.history_filter.currentIndexChanged.connect(self.history_filters_changed)
        filters.addWidget(self.history_filter)
        self.history_count = hint()
        filters.addStretch()
        filters.addWidget(self.history_count)
        layout.addLayout(filters)
        self.history = table(["任务", "开始时间 · 北京时间", "耗时", "结果", "采集条数", "触发方式"])
        self.history.setAccessibleName("采集运行记录")
        self.history.itemSelectionChanged.connect(self.select_history)
        layout.addWidget(self.history, 1)
        self.history_pager = Pager()
        self.history_pager.changed.connect(self.change_page)
        layout.addWidget(self.history_pager)
        self.history_empty = hint()
        layout.addWidget(self.history_empty)
        layout.addWidget(QLabel("运行详情"))
        self.history_detail = QTextEdit()
        accessible(self.history_detail, "采集运行详情")
        self.history_detail.setReadOnly(True)
        self.history_detail.setMinimumHeight(140)
        self.history_detail.setMaximumHeight(210)
        self.history_detail.setPlaceholderText("选择一条记录，查看结束时间、批次信息及完整错误原因。")
        layout.addWidget(self.history_detail)
        return page

    def history_filters_changed(self):
        if self.data and "total" not in self.data:  # Standalone in-memory snapshots.
            self.render_history()
        else:
            self.filters_changed()

    def render_history(self):
        if not self.data:
            return
        names = {j["id"]: j["name"] for j in self.data.get("projects", self.data["jobs"])}
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
        if "download_seconds" in result:
            lines.append(f"本次下载与校验：{result['download_seconds']:.1f} 秒 · "
                         f"等待归档确认：{result.get('archive_wait_seconds', 0):.1f} 秒")
        if "network" in record:
            network = record["network"]
            lines.append(f"请求尝试：代理 {network.get('proxy_requests', 0)} 次 · "
                         f"直连 {network.get('direct_requests', 0)} 次 · "
                         f"其中自动回退 {network.get('fallback_requests', 0)} 次")
        if error:
            lines.extend(["", "完整错误原因：", error])
        elif record["status"] == "paused":
            lines.extend(["", "已暂停并保留断点；启用任务并保存后，可以继续采集。"])
        elif record["status"] == "complete":
            lines.extend(["", "数据已通过校验并归档，可到数据目录打开对应结果。"])
        detail = "\n".join(lines)
        if detail != self.history_detail.toPlainText():
            self.history_detail.setPlainText(detail)


    build_view = _history_page

    def render_content(self):
        jobs = self.data["jobs"]
        self.render_history()
        record_projects = {job["id"]: job for job in self.data.get("projects", jobs)}
        for record in self.data["history"]:
            record_projects.setdefault(record["task_id"], {"id": record["task_id"], "name": record["task_id"]})
        self.archive_records.set_projects(record_projects.values())
        self.error_records.set_projects(record_projects.values())

    @property
    def pager(self):
        return self.history_pager

    def initialize_state(self):
        self.history_records = []
        self.history_selection = None

    def _query_args(self):
        return ("history", "", "", "", self.history_filter.currentData(), self.offset, 25,
                self.history_task.currentData())

    def summary_text(self):
        return "每项目：采集 100 条 · 归档 100 条 · 错误 300 条 · 仅存内存，Redis 重启后丢失"
