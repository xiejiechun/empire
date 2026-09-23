from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageContribution:
    id: str
    title: str
    factory: Callable[[Any], Any]
    group: str = "工作台"
    order: int = 0
    description: str = ""
