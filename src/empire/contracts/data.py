"""Versioned ingestion envelope and deterministic dataset identity."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UnsupportedSchema(RuntimeError):
    """A durable message needs a schema reader that is not currently available."""


class BackpressureError(RuntimeError):
    """A producer must pause while durable storage is at capacity."""


class StaleCheckpointError(RuntimeError):
    """Re-read the durable cursor before retrying a publication."""


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=16, max_length=64)
    source: str = Field(min_length=1, max_length=80)
    dataset: str = Field(min_length=1, max_length=80)
    schema_version: int = Field(default=1, ge=1)
    business_key: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(min_length=64, max_length=64)
    job_key: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=80)
    batch_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    source_event_time: datetime | None = None
    available_at: datetime | None = None
    availability_basis: str = "observed"
    source_url: str | None = None
    source_record_id: str | None = None
    raw_payload: dict[str, Any]

    @field_validator("observed_at", "source_event_time", "available_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamps must include a timezone")
            return value.astimezone(UTC)
        return value


def make_envelope(
    *, source: str, dataset: str, business_key: str, job_key: str,
    run_id: str, batch_id: str, payload: dict[str, Any],
) -> Envelope:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    content_hash = hashlib.sha256(encoded.encode()).hexdigest()
    identity = json.dumps([source, dataset, 1, business_key, content_hash], separators=(",", ":"))
    now = datetime.now(UTC)
    return Envelope(
        event_id=hashlib.sha256(identity.encode()).hexdigest(),
        source=source, dataset=dataset, business_key=business_key, content_hash=content_hash,
        job_key=job_key, run_id=run_id, batch_id=batch_id,
        observed_at=now, available_at=now, raw_payload=payload,
    )
