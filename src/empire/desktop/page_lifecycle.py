"""One shell-owned lifecycle for contributed pages and their read-only work."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea, QStackedWidget, QWidget


def _owners(page: QWidget) -> list[QWidget]:
    return [page, *page.findChildren(QWidget)]


def _clear_cancelled_references(owner: QWidget, cancelled: set[Future[Any]]) -> None:
    """Detach cancelled read futures; mutation futures are never passed here."""
    for name, value in vars(owner).items():
        if isinstance(value, Future) and value in cancelled:
            setattr(owner, name, None)
        elif isinstance(value, dict):
            for key, item in list(value.items()):
                if isinstance(item, Future) and item in cancelled:
                    value.pop(key, None)


def deactivate_page(page: QWidget) -> None:
    if not getattr(page, "_empire_page_active", False):
        return
    page._empire_page_active = False
    timers = {}
    for timer in page.findChildren(QTimer):
        if timer.isActive():
            timers[timer] = timer.interval()
            timer.stop()
    page._empire_page_timers = timers
    for owner in _owners(page):
        scope = getattr(owner, "query_scope", None)
        if scope is not None:
            _clear_cancelled_references(owner, set(scope.cancel_all()))
    hook = getattr(page, "page_deactivated", None)
    if callable(hook):
        hook()


def activate_page(page: QWidget) -> None:
    if getattr(page, "_empire_page_active", False):
        return
    page._empire_page_active = True
    timers = getattr(page, "_empire_page_timers", None)
    if timers is not None:
        for timer, interval in list(timers.items()):
            if timer.parent() is not None:
                timer.start(interval)
                QTimer.singleShot(0, timer.timeout.emit)
        timers.clear()
    hook = getattr(page, "page_activated", None)
    if callable(hook):
        hook()


def capture_page_state(page: QWidget) -> Any:
    capture = getattr(page, "save_ui_state", None)
    return capture() if callable(capture) else None


def restore_page_state(page: QWidget, state: Any) -> None:
    restore = getattr(page, "restore_ui_state", None)
    if state is not None and callable(restore):
        restore(state)


class ReadPageLru:
    """Track only disposable read pages; editors remain shell-persistent."""

    def __init__(self, limit: int = 8) -> None:
        if limit < 1:
            raise ValueError("Page cache limit must be positive")
        self.limit = limit
        self.used: OrderedDict[str, None] = OrderedDict()

    def touch(self, page_id: str, policy: str) -> None:
        self.used.pop(page_id, None)
        if policy == "lru":
            self.used[page_id] = None

    def remove(self, page_id: str) -> None:
        self.used.pop(page_id, None)

    def victims(self, current: str | None) -> list[str]:
        result = []
        while len(self.used) > self.limit:
            page_id, _ = self.used.popitem(last=False)
            if page_id == current:
                self.used[page_id] = None
                continue
            result.append(page_id)
        return result


class PageRegistry:
    """Own lazy page widgets, activation, saved read-page state, and eviction."""

    def __init__(self, stack: QStackedWidget, *, read_limit: int = 8) -> None:
        self.stack = stack
        self.widgets: dict[str, QWidget] = {}
        self.containers: dict[str, QScrollArea] = {}
        self.states: dict[str, Any] = {}
        self.current_id: str | None = None
        self.lru = ReadPageLru(read_limit)

    def show(self, page_id: str, definition: Any, create: Any) -> QWidget:
        if self.current_id != page_id and self.current_id in self.widgets:
            deactivate_page(self.widgets[self.current_id])
        if page_id not in self.widgets:
            widget = create()
            restore_page_state(widget, self.states.get(page_id))
            container = QScrollArea()
            container.setWidgetResizable(True)
            container.setFrameShape(QScrollArea.Shape.NoFrame)
            container.setWidget(widget)
            self.stack.addWidget(container)
            self.widgets[page_id] = widget
            self.containers[page_id] = container
        self.current_id = page_id
        self.stack.setCurrentWidget(self.containers[page_id])
        activate_page(self.widgets[page_id])
        self.lru.touch(page_id, definition.cache_policy)
        for victim in self.lru.victims(page_id):
            self.remove(victim, remember=True)
        return self.widgets[page_id]

    def remove(self, page_id: str, *, remember: bool = False) -> None:
        widget = self.widgets.pop(page_id, None)
        if widget is not None:
            deactivate_page(widget)
            if remember:
                self.states[page_id] = capture_page_state(widget)
        container = self.containers.pop(page_id, None)
        if container is not None:
            self.stack.removeWidget(container)
            container.deleteLater()
        self.lru.remove(page_id)
        if self.current_id == page_id:
            self.current_id = None
        if not remember:
            self.states.pop(page_id, None)

    def deactivate_current(self) -> None:
        if self.current_id in self.widgets:
            deactivate_page(self.widgets[self.current_id])
