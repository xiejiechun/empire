import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from empire.build_info import build_summary
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.core.redaction import Redactor, redact
from empire.plugins.ui.common import accessible, local_date, rows, table
from empire.plugins.ui.plugin import UiPlugin

STATES = {"RUNNING": "已启用", "STOPPED": "已停用", "FAILED": "运行失败",
          "DEGRADED": "运行异常",
          "BLOCKED": "依赖未就绪", "STARTING": "启动中", "STOPPING": "停止中"}


def category(ident):
    return {"infra": "基础服务", "pipeline": "数据管道", "collector": "采集来源",
            "collection": "采集管理", "data": "数据查询", "dataset": "数据规范",
            "ui": "界面"}.get(ident.split(".")[0], "其他")


class SystemStatusPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        layout = QVBoxLayout(self)
        title = QLabel("运行状态")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("检查服务连接、入库进度和需要处理的异常。")
        note.setObjectName("muted")
        layout.addWidget(note)
        build_text, build_detail = build_summary()
        self.build_info = QLabel(build_text)
        self.build_info.setObjectName("muted")
        self.build_info.setToolTip(build_detail)
        self.build_info.setAccessibleName("当前 Empire 构建")
        self.build_info.setAccessibleDescription(build_detail)
        layout.addWidget(self.build_info)
        grid = QGridLayout()
        self.values = {}
        for index, (key, label) in enumerate((("redis", "缓存与进度服务"), ("mysql", "持久化存储"),
                                              ("archive", "自动归档"))):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 16, 16, 16)
            box.addWidget(QLabel(label))
            value = QLabel("检查中")
            value.setObjectName("sectionTitle")
            box.addWidget(value)
            self.values[key] = value
            grid.addWidget(card, 0, index)
        layout.addLayout(grid)
        self.metrics = table(["运行指标", "当前值"])
        self.metrics.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.metrics, 1)
        actions = QHBoxLayout()
        flush = QPushButton("立即归档")
        flush.clicked.connect(lambda: shell.command("flush"))
        actions.addWidget(flush)
        plugins = QPushButton("查看插件状态")
        plugins.clicked.connect(lambda: shell.navigate("plugins"))
        actions.addWidget(plugins)
        actions.addStretch()
        layout.addLayout(actions)
        self.issues = QLabel()
        self.issues.setWordWrap(True)
        layout.addWidget(self.issues)
        self.connections = QLabel()
        self.connections.setWordWrap(True)
        self.connections.setObjectName("muted")
        layout.addWidget(self.connections)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    def tick(self):
        snapshot = self.shell.runtime.snapshot()
        plugins = {p["id"]: p for p in snapshot.get("plugins", [])}
        for key, ident in (("redis", "infra.redis"), ("mysql", "infra.mysql"), ("archive", "pipeline.archive")):
            plugin = plugins.get(ident, {})
            value = STATES.get(plugin.get("state"), "未就绪")
            if value == "已启用" and (plugin.get("error") or plugin.get("health", {}).get("error")):
                value = "需要处理"
            self.values[key].setText(value)
        cache = plugins.get("infra.redis", {}).get("health", {})
        archive = plugins.get("pipeline.archive", {}).get("health", {})
        lanes = plugins.get("infra.mysql", {}).get("health", {}).get("lanes", {})
        sql_metrics = []
        for name, label in (("read", "数据库浏览"), ("control", "数据库归档与配置")):
            lane = lanes.get(name, {})
            sql_metrics.extend([
                (f"{label}执行 / 等待", f"{lane.get('active', 0)} / {lane.get('waiting', 0)}"),
                (f"{label}容量 / 满队拒绝", f"{lane.get('capacity', '—')} / {lane.get('rejected', 0)}")])
        ratio = cache.get("memory_ratio")
        rows(self.metrics, [("待归档消息", cache.get("queued", "—")),
            ("等待完整列表的批次", archive.get("staging_batches", "—")),
            ("归档扫描待继续", "是，正在分轮处理" if archive.get("scan_more") else "否"),
            ("归档已索引消息", archive.get("indexed_messages", 0)),
            ("契约隔离消息", archive.get("isolated_messages", 0)),
            ("契约隔离项目", "、".join(archive.get("blocked_projects", [])) or "无"),
            ("可调度 / 等待重试项目", f"{archive.get('ready_projects', 0)} / {archive.get('retry_projects', 0)}"),
            ("最近一轮扫描条数 / KiB", f"{archive.get('scan_messages', 0)} / {archive.get('scan_bytes', 0) / 1024:.1f}"),
            ("最近一轮处理单元", archive.get("work_units", 0)),
            ("本次启动已确认消息", archive.get("archived", 0)),
            ("本次记录的归档错误", archive.get("errors", 0)),
            ("最近归档成功（北京时间）", local_date(archive["last_success"])
             if archive.get("last_success") else "本次启动尚无归档"),
            ("共享 Redis 服务内存使用率", f"{ratio:.1%}" if ratio is not None else "—")] + sql_metrics)
        errors = [f"{p['name']}：{redact(p.get('error') or p.get('health', {}).get('error'), self.shell.cfg)}"
                  for p in plugins.values() if p.get("error") or p.get("health", {}).get("error")]
        if snapshot.get("error"):
            errors.append(redact(snapshot["error"], self.shell.cfg))
        self.issues.setText("需要处理\n" + "\n".join(errors) if errors else "当前未报告运行异常。")
        cache_cfg, db_cfg = self.shell.cfg.get("redis", {}), self.shell.cfg.get("mysql", {})
        self.connections.setText(
            f"Redis  {cache_cfg.get('host', '—')}:{cache_cfg.get('port', '—')}  ·  "
            f"MySQL  {db_cfg.get('host', '—')}:{db_cfg.get('port', '—')} / {db_cfg.get('database', '—')}\n"
            "连接地址与容量保护在本地配置文件中管理；密码不在界面展示。")


class PluginsPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.visible_plugins = shell, []
        layout = QVBoxLayout(self)
        title = QLabel("插件管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("高级维护功能。日常采集启停与计划请在“采集任务”管理。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.filter = QComboBox()
        accessible(self.filter, "按插件分类筛选")
        self.filter.addItems(["全部分类", "采集来源", "采集管理", "数据查询", "数据规范", "数据管道", "基础服务", "界面", "其他"])
        self.filter.currentIndexChanged.connect(self.tick)
        layout.addWidget(self.filter)
        self.table = table(["插件", "分类", "状态"])
        for column, width in ((1, 150), (2, 130)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.table, 1)
        self.description = QLabel("选择插件查看用途和依赖。")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        actions = QHBoxLayout()
        self.buttons = {}
        for label, command in (("启用插件", "start"), ("停用插件", "stop"), ("停用插件及依赖功能", "cascade")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, action=command: self.operate(action))
            self.buttons[command] = button
            actions.addWidget(button)
        layout.addLayout(actions)
        self.technical = QCheckBox("显示技术诊断")
        layout.addWidget(self.technical)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(150)
        self.diagnostics.hide()
        self.technical.toggled.connect(self.diagnostics.setVisible)
        layout.addWidget(self.diagnostics)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    def save_ui_state(self):
        selected = self.selected()
        return {"filter": self.filter.currentText(),
                "selected": selected["id"] if selected else None,
                "technical": self.technical.isChecked()}

    def restore_ui_state(self, state):
        self.filter.setCurrentIndex(max(0, self.filter.findText(state["filter"])))
        self.technical.setChecked(state["technical"])
        self._restore_plugin_id = state["selected"]

    def selected(self):
        index = self.table.currentRow()
        return self.visible_plugins[index] if 0 <= index < len(self.visible_plugins) else None

    def tick(self):
        selected = self.selected()
        ident = getattr(self, "_restore_plugin_id", None) or (selected["id"] if selected else None)
        self._restore_plugin_id = None
        plugins = self.shell.runtime.snapshot().get("plugins", [])
        choice = self.filter.currentText()
        self.visible_plugins = [p for p in plugins if choice == "全部分类" or category(p["id"]) == choice]
        self.table.blockSignals(True)
        rows(self.table, [[p["name"], category(p["id"]), STATES.get(p["state"], p["state"])]
                          for p in self.visible_plugins])
        if self.visible_plugins:
            index = next((i for i, p in enumerate(self.visible_plugins) if p["id"] == ident), 0)
            self.table.selectRow(index)
        self.table.blockSignals(False)
        self.show_detail()

    def show_detail(self):
        plugin = self.selected()
        for action, button in self.buttons.items():
            button.setEnabled(bool(plugin and (plugin.get("can_start", False) if action == "start"
                                                else plugin["state"] != "STOPPED")))
        if not plugin:
            self.description.setText("此分类暂无插件。")
            self.diagnostics.clear()
            return
        self.description.setText(plugin.get("description", "") or plugin["name"])
        if plugin.get("error"):
            self.description.setText(self.description.text() + "\n" + redact(plugin["error"], self.shell.cfg))
        if plugin["state"] == "FAILED" and not plugin.get("can_start", False):
            self.description.setText(self.description.text() + "\n关键任务或资源异常；请先正常停用并处理原因，再启用。")
        diagnostic = json.dumps(Redactor.from_config(self.shell.cfg).value(
            {"标识": plugin["id"], "依赖能力": plugin.get("requires", []),
             "运行状态": plugin.get("health", {})}), ensure_ascii=False, indent=2)
        if self.diagnostics.toPlainText() != diagnostic:
            self.diagnostics.setPlainText(diagnostic)

    def operate(self, action):
        plugin = self.selected()
        if plugin:
            self.shell.command(action, plugin["id"])


class SystemUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.system", "系统管理界面", provides=("ui.pages.system",), autostart=True,
        description="系统管理界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("system", "运行状态", SystemStatusPage, "系统设置", 0,
                             "服务连接与归档状态", cache_policy="lru"),
            PageContribution("plugins", "插件管理", PluginsPage, "系统设置", 1,
                             "按功能分类维护内部插件", cache_policy="lru"),
        )
