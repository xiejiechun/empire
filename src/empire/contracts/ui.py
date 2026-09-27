from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class NavigationContext:
    task_id: str = ""

    def __post_init__(self):
        if len(self.task_id) > 100:
            raise ValueError("Navigation task ID is too long")


@dataclass(frozen=True)
class NavigationTarget:
    page_id: str
    context: NavigationContext = NavigationContext()

    def __post_init__(self):
        if not self.page_id:
            raise ValueError("Navigation target page ID is required")


@dataclass(frozen=True)
class PageContribution:
    id: str
    title: str
    factory: Callable[[Any], Any]
    group: str = "工作台"
    order: int = 0
    description: str = ""
    top_level: bool = False
    catalogued: bool = False
    category: str = "其他"
    source: str = ""
    cache_policy: Literal["persistent", "lru"] = "persistent"
    management: NavigationTarget | None = None

    def __post_init__(self):
        if self.cache_policy not in ("persistent", "lru"):
            raise ValueError("Page cache policy must be persistent or lru")
