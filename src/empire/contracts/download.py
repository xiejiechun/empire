"""Explicit bounded response contracts, independent of source and proxy protocol."""
from dataclasses import dataclass

MiB = 1024 * 1024
CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class ResponsePolicy:
    max_body_bytes: int = 2 * MiB
    max_wire_bytes: int = 2 * MiB

    def __post_init__(self):
        for value in (self.max_body_bytes, self.max_wire_bytes):
            if type(value) is not int or not 1 <= value <= 1024 * MiB:
                raise ValueError("响应字节上限必须为 1～1 GiB 的整数")

    @property
    def reservation_bytes(self):
        # Cover bytearray growth/reallocation, the final bytes copy and bounded
        # decoder/sample workspaces; this is not a cap on Python/HTTP stack RSS.
        return 3 * self.max_body_bytes + 4 * CHUNK_BYTES


@dataclass(frozen=True)
class FilePolicy(ResponsePolicy):
    max_body_bytes: int = 256 * MiB
    max_wire_bytes: int = 256 * MiB
    filename: str = ""
    signature: bytes = b""
    expected_sha256: str | None = None

    @property
    def reservation_bytes(self):
        # A file never reserves its complete size in the memory budget.
        return 4 * CHUNK_BYTES


STOCK_RESPONSE = ResponsePolicy(max_body_bytes=1 * MiB, max_wire_bytes=1 * MiB)
NEWS_RESPONSE = ResponsePolicy(max_body_bytes=4 * MiB, max_wire_bytes=4 * MiB)
CALENDAR_RESPONSE = ResponsePolicy(max_body_bytes=512 * 1024, max_wire_bytes=512 * 1024)
