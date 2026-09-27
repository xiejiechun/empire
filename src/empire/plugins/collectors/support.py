"""Small lifecycle helpers shared by collectors; business rules stay in each source plugin."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from typing import Any

from empire.contracts.collector import (
    ArchiveStatus,
    ArchiveStatusCall,
    Checkpoint,
    CollectionRecords,
    ErrorText,
    IngestPublisher,
    QueueReservation,
)
from empire.contracts.data import BackpressureError, BatchReservationError, Envelope


async def wait_for_capacity(
    ingest: IngestPublisher,
    stats: MutableMapping[str, Any],
    *,
    reservation: QueueReservation | None = None,
    error_text: ErrorText = str,
    retry_seconds: float = 5,
) -> None:
    """Wait only for recoverable queue pressure and keep the collector state explicit."""
    while True:
        try:
            await ingest.ensure_capacity(reservation=reservation)
            stats.update(status="collecting", error="")
            return
        except BatchReservationError:
            raise
        except BackpressureError as exc:
            stats.update(status="paused", error=error_text(exc))
            await asyncio.sleep(retry_seconds)


async def publish_with_capacity(
    ingest: IngestPublisher,
    stats: MutableMapping[str, Any],
    envelopes: list[Envelope],
    *,
    job_key: str,
    expected_revision: int,
    cursor: dict[str, Any],
    reservation: QueueReservation | None = None,
    error_text: ErrorText = str,
    retry_seconds: float = 5,
) -> Checkpoint:
    """Publish through the one ingest path, waiting only when capacity can recover."""
    while True:
        try:
            return await ingest.publish_page(
                envelopes,
                job_key=job_key,
                expected_revision=expected_revision,
                cursor=cursor,
                reservation=reservation,
            )
        except BatchReservationError:
            raise
        except BackpressureError:
            await wait_for_capacity(
                ingest,
                stats,
                reservation=reservation,
                error_text=error_text,
                retry_seconds=retry_seconds,
            )


async def wait_for_archive(
    read_status: ArchiveStatusCall, *, retry_seconds: float,
) -> ArchiveStatus:
    """Wait for the common complete/invalid archive contract."""
    while True:
        status = await read_status()
        if status and status.get("status") == "complete":
            return status
        if status and status.get("status") == "invalid":
            raise ValueError(status.get("error_text") or "归档数据无效")
        await asyncio.sleep(retry_seconds)


async def record_error_safely(
    records: CollectionRecords,
    stats: MutableMapping[str, Any],
    project_id: str,
    error: BaseException,
    *,
    stage: str,
    unavailable_message: str,
    fields: dict[str, Any] | None = None,
) -> bool:
    """Record one collector failure without hiding the original exception."""
    if getattr(error, "diagnostic_recorded", False):
        return False
    try:
        await records.add_error(
            project_id,
            stage=stage,
            error=str(error),
            **(fields or {}),
        )
        stats.pop("diagnostic_error", None)
        return True
    except Exception:
        stats["diagnostic_error"] = unavailable_message
        return False
