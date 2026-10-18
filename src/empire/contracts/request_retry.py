"""Shared task retry limits and bounded request timing."""

MAX_REQUEST_RETRIES = 100


def retry_delay(retry: int) -> int:
    return 2 ** (retry - 1) if retry <= 5 else 30


def request_timeout(retries: int) -> int:
    # Preserve the existing two-retry deadline; each extra retry gets room
    # for the 30-second HTTP timeout and the capped backoff.
    return 120 + max(0, retries - 2) * 60
