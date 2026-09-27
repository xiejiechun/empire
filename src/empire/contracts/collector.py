"""Typed boundaries shared by source collectors without imposing a base class."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from empire.contracts.data import Envelope


class Checkpoint(TypedDict):
    revision: int
    cursor: dict[str, Any]


class ArchiveStatus(TypedDict, total=False):
    status: Literal["complete", "invalid"]
    error_text: str
    page: int


class StockRunResult(TypedDict):
    snapshot_id: str
    collected: int
    expected_count: int
    pages: NotRequired[int]
    download_seconds: NotRequired[float]
    archive_wait_seconds: NotRequired[float]


class NewsRunResult(TypedDict):
    collected: int
    pages: int
    high_watermark: int
    batch_id: str


class CalendarRunResult(TypedDict):
    collected: int
    pages: int
    batch_id: str
    start_month: str
    end_month: str
    maintenance_start: str


class QueueReservation(Protocol):
    job_key: str
    remaining_entries: int

    async def release(self) -> None: ...


class IngestPublisher(Protocol):
    async def checkpoint(self, job_key: str) -> Checkpoint: ...

    async def advance_checkpoint(
        self, *, job_key: str, expected_revision: int, cursor: dict[str, Any],
    ) -> Checkpoint: ...

    async def ensure_capacity(
        self, incoming: int = 1, reservation: QueueReservation | None = None,
    ) -> None: ...

    async def publish_page(
        self, envelopes: list[Envelope], *, job_key: str, expected_revision: int,
        cursor: dict[str, Any], reservation: QueueReservation | None = None,
    ) -> Checkpoint: ...

    async def reserve_batch(self, job_key: str, entries: int) -> QueueReservation: ...


class ArchiveConfirmation(Protocol):
    async def stock_status(
        self, source: str, job_key: str, project_id: str, snapshot_id: str,
    ) -> ArchiveStatus | None: ...

    async def page_status(
        self, source: str, job_key: str, project_id: str, batch_id: str, page: int,
    ) -> ArchiveStatus | None: ...


class CollectionRecords(Protocol):
    def sanitize_text(self, value: Any) -> str: ...

    async def add_error(
        self, project_id: str, *, stage: str, error: str, **fields: Any,
    ) -> dict[str, Any]: ...


ArchiveStatusCall = Callable[[], Awaitable[ArchiveStatus | None]]
ErrorText = Callable[[BaseException], str]
