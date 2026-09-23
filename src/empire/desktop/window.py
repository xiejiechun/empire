from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from empire.core.config import redact

STYLE = """
QMainWindow, QWidget { background: #0d1422; color: #e3eaf5; font: 10pt 'Microsoft YaHei UI'; }
QLabel, QCheckBox { background: transparent; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #95a7bd; border-radius: 3px; background: #162237; }
QCheckBox::indicator:checked { background: #61dfc4; border: 2px solid #a6f4dc; }
QCheckBox::indicator:hover { border-color: #61dfc4; }
QWidget#sidebar { background: #101b2e; border-radius: 12px; }
QLabel#brand { font-size: 22pt; font-weight: 700; color: #61dfc4; padding: 8px 0; }
QLabel#muted { color: #95a7bd; }
QLabel#breadcrumb { color: #95a7bd; font-size: 9pt; padding-bottom: 6px; }
QLabel#pageTitle { font-size: 21pt; font-weight: 600; margin-bottom: 6px; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 600; }
QLabel#cardValue { font-size: 23pt; font-weight: 600; color: #73e2c7; }
QFrame#card, QGroupBox { background: #142136; border: 1px solid #283950; border-radius: 8px; }
QFrame#card QLabel, QGroupBox QLabel { background: transparent; }
QListWidget { background: transparent; border: none; padding: 0; outline: none; }
QListWidget::item { padding: 11px 14px; margin: 2px 0; border-radius: 6px; }
QListWidget::item:selected { background: #20483f; color: #a6f4dc; }
QListWidget::item:hover:enabled { background: #1c3044; }
QPushButton { background: #20324d; border: 1px solid #344c6b; padding: 8px 14px; border-radius: 6px; }
QPushButton:hover { background: #2c4364; }
QPushButton:focus { border: 1px solid #73e2c7; }
QPushButton:disabled { color: #62738b; background: #152237; }
QPushButton#primary { background: #167e6d; border-color: #229d88; color: white; }
QPushButton#primary:disabled { color: #62738b; background: #152237; border-color: #344c6b; }
QSpinBox:disabled, QTimeEdit:disabled { color: #62738b; background: #101b2e; }
QTableWidget, QTextEdit, QPlainTextEdit { background: #111e31; alternate-background-color: #142136; border: 1px solid #263650; border-radius: 6px; }
QTableWidget { gridline-color: #263650; selection-background-color: #245347; selection-color: #e3eaf5; }
QTableWidget::item { padding: 5px; }
QHeaderView::section { background: #1a2a42; color: #b8c9de; border: none; padding: 10px; }
QTabWidget::pane { border: 1px solid #263650; }
QTabBar::tab { padding: 10px 22px; background: #162237; }
QTabBar::tab:selected { background: #24524e; color: #a6f4dc; }
QGroupBox { margin-top: 14px; padding: 10px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; }
QLineEdit, QSpinBox, QTimeEdit, QComboBox { padding: 6px; background: #162237; border: 1px solid #344c6b; border-radius: 4px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus { border-color: #73e2c7; }
QScrollArea { border: none; }
QProgressBar { border: none; background: #263650; border-radius: 4px; }
QProgressBar::chunk { background: #42bca0; border-radius: 4px; }
QStatusBar { background: #101b2e; color: #95a7bd; }
QSplitter::handle { background: #263650; }
"""

GROUP_ORDER = {"工作台": 0, "数据中心": 1, "采集管理": 2, "系统管理": 3}
ACTION_NAMES = {"start": "启用插件", "stop": "停用插件", "cascade": "停止插件及依赖功能",
                "flush": "立即归档", "shutdown": "退出应用"}


class MainWindow(QMainWindow):
    """Desktop shell: navigation and lifecycle only; pages come from UI plugins."""

    def __init__(self, runtime, cfg):
        super().__init__()
        self.runtime, self.cfg = runtime, cfg
        self.pending = []
        self.shutting_down = self.can_close = False
        self.contributed_ids = ()
        self.page_widgets = {}
        self.current_page_id = None
        self.setWindowTitle("Empire · 投资研究工作台")
        self.resize(1320, 860)
        self.setMinimumSize(1060, 720)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 20, 12)
        layout.setSpacing(24)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 14, 14, 14)
        brand = QLabel("EMPIRE")
        brand.setObjectName("brand")
        side.addWidget(brand)
        label = QLabel("个人投资研究")
        label.setObjectName("muted")
        side.addWidget(label)
        self.nav = QListWidget()
        side.addWidget(self.nav, 1)
        self.service_status = QLabel("正在连接本地服务…")
        self.service_status.setWordWrap(True)
        self.service_status.setObjectName("muted")
        side.addWidget(self.service_status)
        label = QLabel("A 股 · 本地工作空间")
        label.setObjectName("muted")
        side.addWidget(label)
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        self.breadcrumb = QLabel("工作台")
        self.breadcrumb.setObjectName("breadcrumb")
        content.addWidget(self.breadcrumb)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        layout.addLayout(content, 1)
        fallback = QWidget()
        box = QVBoxLayout(fallback)
        title = QLabel("正在准备工作空间")
        title.setObjectName("pageTitle")
        box.addWidget(title)
        self.startup_status = QLabel("连接本地服务后，这里会显示你的数据与采集任务。")
        self.startup_status.setWordWrap(True)
        box.addWidget(self.startup_status)
        retry = QPushButton("恢复界面插件")
        retry.clicked.connect(lambda: self.command("start", "ui.workspace"))
        box.addWidget(retry)
        box.addStretch()
        self.pages.addWidget(fallback)
        self.nav.currentItemChanged.connect(self._selected)
        for key, page_id in (("Alt+1", "home"), ("Alt+2", "stocks"), ("Alt+3", "collection")):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda route=page_id: self.navigate(route))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _selected(self, item, previous=None):
        if not item:
            return
        ident = item.data(Qt.ItemDataRole.UserRole)
        if ident in self.page_widgets:
            self.current_page_id = ident
            self.pages.setCurrentWidget(self.page_widgets[ident])
            self.breadcrumb.setText(item.data(Qt.ItemDataRole.UserRole + 1))

    def navigate(self, page_id):
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == page_id:
                self.nav.setCurrentItem(item)
                return True
        self.statusBar().showMessage("此功能尚未就绪，请检查界面插件状态。", 6000)
        return False

    def command(self, action, plugin_id=""):
        if self.shutting_down:
            return
        try:
            future = self.runtime.command(action, plugin_id)
            self.pending.append((action, future))
            self.statusBar().showMessage(f"正在执行：{ACTION_NAMES.get(action, action)}")
        except Exception as exc:
            self.statusBar().showMessage(redact(exc, self.cfg))

    def _sync_pages(self):
        contributions = sorted(self.runtime.page_contributions(),
            key=lambda p: (GROUP_ORDER.get(p.group, 9), p.order, p.id))
        signature = tuple((p.id, p.title, p.group, p.order) for p in contributions)
        if signature == self.contributed_ids:
            return
        selected = self.current_page_id
        valid = {p.id for p in contributions}
        for ident in list(self.page_widgets):
            if ident not in valid:
                widget = self.page_widgets.pop(ident)
                self.pages.removeWidget(widget)
                widget.deleteLater()
        for page in contributions:
            if page.id not in self.page_widgets:
                widget = page.factory(self)
                self.pages.addWidget(widget)
                self.page_widgets[page.id] = widget
        self.nav.blockSignals(True)
        self.nav.clear()
        last_group = None
        for page in contributions:
            if page.group != last_group:
                heading = QListWidgetItem(page.group)
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                heading.setForeground(QColor("#8295b0"))
                font = heading.font()
                font.setPointSize(9)
                heading.setFont(font)
                self.nav.addItem(heading)
                last_group = page.group
            item = QListWidgetItem(page.title)
            item.setData(Qt.ItemDataRole.UserRole, page.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{page.group}  /  {page.title}")
            item.setToolTip(page.description or page.title)
            self.nav.addItem(item)
        self.nav.blockSignals(False)
        self.contributed_ids = signature
        if contributions:
            self.navigate(selected if selected in valid else ("home" if "home" in valid else contributions[0].id))
        else:
            self.current_page_id = None
            self.pages.setCurrentIndex(0)
            self.startup_status.setText("界面插件未就绪或已停用。可恢复插件以重新打开工作空间。")

    def refresh(self):
        for action, future in list(self.pending):
            if not future.done():
                continue
            self.pending.remove((action, future))
            try:
                future.result()
                self.statusBar().showMessage(f"已完成：{ACTION_NAMES.get(action, action)}", 6000)
            except Exception as exc:
                message = redact(exc, self.cfg)
                self.statusBar().showMessage(message)
                if action == "shutdown":
                    self.shutting_down = False
                    QMessageBox.warning(self, "退出尚未完成", message)
        if self.shutting_down and self.runtime.closed.is_set():
            self.can_close = True
            self.close()
            return
        snapshot = self.runtime.snapshot()
        plugins = snapshot.get("plugins", [])
        stores = [p for p in plugins if p["id"] in ("infra.redis", "infra.mysql")]
        issues = [p for p in plugins if p.get("error") or p.get("health", {}).get("error")]
        self.service_status.setText("有运行异常 · 请查看运行状态" if issues else
            ("本地服务已连接" if len(stores) == 2 and all(p["state"] == "RUNNING" for p in stores)
             else "本地服务连接中 / 未就绪"))
        if snapshot.get("error"):
            self.startup_status.setText(redact(snapshot["error"], self.cfg))
        self._sync_pages()

    def closeEvent(self, event):
        if self.can_close or self.runtime.closed.is_set():
            event.accept()
            return
        event.ignore()
        if not self.shutting_down:
            self.shutting_down = True
            self.statusBar().showMessage("正在保存进度、结束归档并关闭连接……")
            self.pending.append(("shutdown", self.runtime.command("shutdown")))
