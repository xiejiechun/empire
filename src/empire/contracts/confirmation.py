"""Explicit status handlers supplied by business bundles before services start."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from sqlalchemy.engine import Engine

from empire.core.identity import safe_project_id

# Only persisted progress remains heterogeneous; service access is structural.
type ConfirmationPayload = dict[str, Any]
_Result = TypeVar('_Result')


class ConfirmationSqlStore(Protocol):
    @property
    def engine(self) -> Engine: ...

    # The existing control lane forwards positional args to its operation.
    # Callable's argument list is deliberately open; the return type is retained.
    def control(
        self, operation: Callable[..., _Result], *args: object,
    ) -> Awaitable[_Result]: ...


class ConfirmationRedisClient(Protocol):
    def get(self, name: str) -> Awaitable[str | bytes | None]: ...


class ConfirmationRedisStore(Protocol):
    @property
    def client(self) -> ConfirmationRedisClient: ...

    @property
    def prefix(self) -> str: ...


class ConfirmationHandler(Protocol):
    # No callback captures a manager, connection, or widget instance.
    def __call__(
        self, mysql: ConfirmationSqlStore, redis: ConfirmationRedisStore,
        source: str, job_key: str, project_id: str, snapshot_id: str,
    ) -> Awaitable[ConfirmationPayload | None]: ...


@dataclass(frozen=True)
class ConfirmationContribution:
    id: str
    handler: ConfirmationHandler

    def __post_init__(self) -> None:
        if not self.id or safe_project_id(self.id) != self.id or not callable(self.handler):
            raise ValueError('归档确认贡献须声明合法身份及处理函数')
