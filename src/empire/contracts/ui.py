from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


@dataclass(frozen=True)
class NavigationContext:
    task_id: str = ""
    unified_code: str = ""
    index_code: str = ""
    source: str = ""
    day: str = ""
    start: str = ""
    end: str = ""
    event_key: str = ""

    def __post_init__(self):
        if len(self.task_id) > 100:
            raise ValueError("Navigation task ID is too long")
        if self.unified_code:
            from empire.contracts.security import split_unified_code
            split_unified_code(self.unified_code)
        if self.index_code:
            from empire.contracts.indices import index_code
            index_code(self.index_code)
            if self.source != 'ths':
                raise ValueError('指数导航必须明确同花顺来源')
        if self.unified_code and self.index_code:
            raise ValueError('不能同时指定股票与指数身份')
        for value in (self.day, self.start, self.end):
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError('导航日期必须为 YYYY-MM-DD')
        if self.start and self.end and self.start > self.end:
            raise ValueError('导航起始日不能晚于截止日')
        if len(self.event_key) > 128 or len(self.source) > 32:
            raise ValueError('导航字段超过长度上限')


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
    database_tables: tuple[str, ...] = ()

    def __post_init__(self):
        if self.cache_policy not in ("persistent", "lru"):
            raise ValueError("Page cache policy must be persistent or lru")
