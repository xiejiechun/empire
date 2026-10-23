"""Deterministic detail review slots; discovery and pending gaps always win."""

import hashlib
from datetime import date

REVIEW_POLICY = 2


def review_due(code: str, stamp: str, status: str | None, through: str) -> bool:
    """Choose a daily slot without persistent last-seen writes or random hash."""
    if status not in {"present", "partial", "source_empty"}:
        return True
    current = date.fromisoformat(through)
    age = (current - date.fromisoformat(stamp)).days
    if age <= 6:
        return True
    if age <= 89:
        period = 7
    elif status in {"partial", "source_empty"}:
        period = 30
    else:
        return False
    bucket = int.from_bytes(hashlib.sha256(f"{code}:{stamp}".encode()).digest(), "big")
    return bucket % period == current.toordinal() % period
