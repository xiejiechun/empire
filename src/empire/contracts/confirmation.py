"""Explicit status handlers supplied by business bundles before services start."""
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from empire.core.identity import safe_project_id


class ConfirmationHandler(Protocol):
    # Infrastructure stores and persisted progress are existing dynamic service
    # boundaries. No callback captures a manager, connection, or widget instance.
    def __call__(self, mysql: Any, redis: Any, source: str, job_key: str,
                 project_id: str, snapshot_id: str) -> Awaitable[dict[str, Any] | None]: ...


@dataclass(frozen=True)
class ConfirmationContribution:
    id: str
    handler: ConfirmationHandler

    def __post_init__(self) -> None:
        if not self.id or safe_project_id(self.id) != self.id or not callable(self.handler):
            raise ValueError('归档确认贡献须声明合法身份及处理函数')
