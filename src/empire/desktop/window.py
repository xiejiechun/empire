from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
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

from empire.contracts.ui import NavigationContext
from empire.core.redaction import redact
from empire.desktop.page_lifecycle import PageRegistry
from empire.desktop.theme import SIDEBAR_WIDTH, desktop_style

GROUP_ORDER = {"工作台": 0, "数据浏览": 1, "采集管理": 2, "系统设置": 3, "说明文档": 4}
ACTION_NAMES = {"start": "启用插件", "stop": "停用插件", "cascade": "停止插件及依赖功能",
                "flush": "立即归档", "shutdown": "退出应用", "restore_ui": "恢复界面插件"}


class MainWindow(QMainWindow):
    """Desktop shell: navigation and lifecycle only; pages come from UI plugins."""

    def __init__(self, runtime, cfg):
        super().__init__()
        self.runtime, self.cfg = runtime, cfg
        self.pending = []
        self.shutting_down = self.can_close = False
        self.contributed_ids = ()
        self.page_definitions = {}
        self.current_page_id = None
        self.group_pages = {}
        self.group_selection = {}
        self.pending_navigation_contexts = {}
        self.setWindowTitle("Empire · 投资研究工作台")
        available = self.screen().availableGeometry()
        self.setMinimumSize(min(640, available.width()), min(360, available.height()))
        self.resize(min(1320, available.width()), min(860, max(1, available.height() - 48)))
        self.setStyleSheet(desktop_style())
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 28, 12)
        layout.setSpacing(28)
        self.root_layout = layout
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 24, 18, 18)
        brand = QLabel("EMPIRE")
        brand.setObjectName("brand")
        side.addWidget(brand)
        label = QLabel("个人投资研究")
        label.setObjectName("muted")
        side.addWidget(label)
        side.addSpacing(28)
        self.nav = QListWidget()
        self.nav.setObjectName("primaryNav")
        self.nav.setAccessibleName("一级导航")
        self.nav.setAccessibleDescription("使用方向键选择功能分组。")
        side.addWidget(self.nav, 1)
        self.service_status = QLabel("正在连接本地服务…")
        self.service_status.setWordWrap(True)
        self.service_status.setObjectName("muted")
        side.addWidget(self.service_status)
        label = QLabel("A 股 · 本地工作空间")
        label.setObjectName("muted")
        side.addWidget(label)
        layout.addWidget(self.sidebar)
        self.content_layout = QVBoxLayout()
        content = self.content_layout
        content.setContentsMargins(0, 24, 0, 0)
        content.setSpacing(12)
        self.breadcrumb = QLabel("工作台")
        self.breadcrumb.setObjectName("breadcrumb")
        content.addWidget(self.breadcrumb)
        self.subnav = QListWidget()
        self.subnav.setObjectName("secondaryNav")
        self.subnav.setAccessibleName("当前分组页面")
        self.subnav.setAccessibleDescription("使用左右方向键切换页面。")
        self.subnav.setFlow(QListWidget.Flow.LeftToRight)
        self.subnav.setFixedHeight(48)
        self.subnav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.subnav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.addWidget(self.subnav)
        self.pages = QStackedWidget()
        self.pages.setAccessibleName("当前页面内容")
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
        retry.clicked.connect(lambda: self.command("restore_ui"))
        box.addWidget(retry)
        box.addStretch()
        self.pages.addWidget(fallback)
        self.page_registry = PageRegistry(self.pages)
        self.page_widgets = self.page_registry.widgets
        self.page_containers = self.page_registry.containers
        self.nav.currentItemChanged.connect(self._group_selected)
        self.subnav.currentItemChanged.connect(self._selected)
        for key, page_id in (("Alt+1", "home"), ("Alt+2", "stocks"), ("Alt+3", "collection"), ("F1", "help")):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda route=page_id: self.navigate(route))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        compact = self.width() < 900
        self.sidebar.setFixedWidth(148 if compact else SIDEBAR_WIDTH)
        self.root_layout.setSpacing(14 if compact else 28)
        self.root_layout.setContentsMargins(0, 0, 12 if compact else 28, 8 if compact else 12)
        self.content_layout.setContentsMargins(0, 12 if compact else 24, 0, 0)

    def _group_selected(self, item, previous=None):
        self.subnav.blockSignals(True)
        self.subnav.clear()
        self.subnav.hide()
        if not item:
            self.subnav.blockSignals(False)
            return
        group = item.data(Qt.ItemDataRole.UserRole)
        pages = self.group_pages.get(group, [])
        selected = self.group_selection.get(group)
        pages = [p for p in pages if not p.catalogued or p.id == selected]
        direct = len(pages) == 1 and pages[0].top_level
        self.subnav.setVisible(bool(pages) and not direct)
        for page in pages:
            child = QListWidgetItem(page.title)
            child.setData(Qt.ItemDataRole.UserRole, page.id)
            child.setData(Qt.ItemDataRole.UserRole + 1, page.title if direct else f"{group}  /  {page.title}")
            child.setToolTip(page.description or page.title)
            self.subnav.addItem(child)
        selected = self.group_selection.get(group)
        row = next((i for i, p in enumerate(pages) if p.id == selected), 0)
        if pages:
            self.subnav.setCurrentRow(row)
            current = self.subnav.currentItem()
        else:
            current = None
        self.subnav.blockSignals(False)
        if current:
            self._selected(current)

    def _selected(self, item, previous=None):
        if not item:
            return
        ident = item.data(Qt.ItemDataRole.UserRole)
        if ident in self.page_definitions:
            definition = self.page_definitions[ident]
            def create():
                try:
                    return definition.factory(self)
                except Exception as exc:
                    return self._page_error(ident, exc)
            page = self.page_registry.show(ident, definition, create)
            self.current_page_id = ident
            group = self.nav.currentItem().data(Qt.ItemDataRole.UserRole)
            self.group_selection[group] = ident
            self.breadcrumb.setText(item.data(Qt.ItemDataRole.UserRole + 1))
            context = self.pending_navigation_contexts.get(ident)
            apply_context = getattr(page, "apply_navigation_context", None)
            if context is not None and callable(apply_context):
                self.pending_navigation_contexts.pop(ident, None)
                apply_context(context)
            elif context is not None and not getattr(page, "_empire_page_error", False):
                self.pending_navigation_contexts.pop(ident, None)
                self.statusBar().showMessage("目标页面不支持此导航上下文。", 6000)

    def _page_error(self, ident, error):
        widget = QWidget()
        widget._empire_page_error = True
        box = QVBoxLayout(widget)
        title = QLabel("此页面暂时无法打开")
        title.setObjectName("pageTitle")
        box.addWidget(title)
        detail = QLabel(redact(error, self.cfg))
        detail.setWordWrap(True)
        detail.setObjectName("muted")
        box.addWidget(detail)
        retry = QPushButton("重试打开页面")
        retry.clicked.connect(lambda: self._retry_page(ident))
        box.addWidget(retry)
        box.addStretch()
        return widget

    def _retry_page(self, ident):
        self.page_registry.remove(ident)
        QTimer.singleShot(0, lambda: self.navigate(ident))

    def navigate(self, page_id, context: NavigationContext | None = None):
        if context is not None:
            self.pending_navigation_contexts[page_id] = context
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            group = item.data(Qt.ItemDataRole.UserRole)
            if any(page.id == page_id for page in self.group_pages[group]):
                self.group_selection[group] = page_id
                if self.nav.currentItem() == item:
                    self._group_selected(item)
                else:
                    self.nav.setCurrentItem(item)
                for index in range(self.subnav.count()):
                    child = self.subnav.item(index)
                    if child.data(Qt.ItemDataRole.UserRole) == page_id:
                        self.subnav.setCurrentItem(child)
                        return True
        self.pending_navigation_contexts.pop(page_id, None)
        self.statusBar().showMessage("此功能尚未就绪，请检查界面插件状态。", 6000)
        return False

    def navigate_management(self, source_page_id):
        source = self.page_definitions.get(source_page_id)
        target = source.management if source is not None else None
        if target is None:
            self.statusBar().showMessage("此数据页面没有登记采集管理入口。", 6000)
            return False
        return self.navigate(target.page_id, target.context)

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
        signature = tuple((p.id, p.title, p.group, p.order, p.top_level, p.catalogued,
                           p.category, p.source, p.cache_policy, p.management) for p in contributions)
        if signature == self.contributed_ids:
            return
        selected = self.current_page_id
        valid = {p.id for p in contributions}
        for ident in list(self.page_widgets):
            if ident not in valid:
                self.page_registry.remove(ident)
                self.pending_navigation_contexts.pop(ident, None)
        self.page_definitions = {p.id: p for p in contributions}
        self.nav.blockSignals(True)
        self.nav.clear()
        self.subnav.clear()
        self.group_pages = {}
        for page in contributions:
            self.group_pages.setdefault(page.group, []).append(page)
        for group in self.group_pages:
            item = QListWidgetItem(group)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.nav.addItem(item)
        self.nav.blockSignals(False)
        self.contributed_ids = signature
        if contributions:
            self.navigate(selected if selected in valid else ("home" if "home" in valid else contributions[0].id))
        else:
            self.page_registry.deactivate_current()
            self.current_page_id = None
            self.subnav.hide()
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
            self.page_registry.deactivate_current()
            self.statusBar().showMessage("正在保存进度、结束归档并关闭连接……")
            self.pending.append(("shutdown", self.runtime.command("shutdown")))
