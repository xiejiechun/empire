import hashlib
import re


def safe_project_id(value: str = "") -> str:
    """Validate an explicit project identity or derive a bounded diagnostic identity."""
    value = str(value or "unknown")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        return value
    return "project-" + hashlib.sha256(value.encode()).hexdigest()[:24]
