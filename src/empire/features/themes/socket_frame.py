"""Bounded framing for the current app protocol, not guest authentication.

Reading a frame does not prove catalog completeness or grant access to its body.
The shared stream downloader owns transport, deadlines, permits and byte limits.
"""
from dataclasses import dataclass


class FrameError(ValueError):
    """Discard the connection after malformed or unsupported framing."""


@dataclass(frozen=True)
class Frame:
    kind: int
    command: int | None
    sequence: int | None
    status: int
    encoding: int
    extensions: tuple[tuple[int, int | str], ...]
    topic: str | None
    body: bytes

    def plaintext(self) -> bytes:
        if self.encoding != 0:
            raise FrameError("Encrypted or unknown encoding requires verified decoding")
        if self.status != 0 or self.kind not in (2, 3):
            raise FrameError("Control or error frame is not a normal response")
        return self.body


class _Cursor:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self.data):
            raise FrameError("Truncated frame metadata")
        result = self.data[self.offset:end]
        self.offset = end
        return result

    def number(self, length: int) -> int:
        return int.from_bytes(self.take(length), "big")

    def text(self) -> str:
        try:
            return self.take(self.number(2)).decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FrameError("Invalid UTF-8 frame metadata") from exc


def _extensions(data: bytes) -> tuple[tuple[int, int | str], ...]:
    cursor = _Cursor(data)
    entries = {}
    while cursor.offset < len(data):
        key = cursor.number(1)
        if key in entries:
            raise FrameError("Duplicate extension")
        if key == 1:
            value = cursor.number(8)
        elif key == 2:
            value = cursor.number(2)
        elif key == 3:
            value = cursor.text()
        else:
            # App extension 4 alters remaining body length. Until its semantics
            # are verified, never consume a guessed length or reuse this socket.
            raise FrameError("Unsupported frame extension")
        entries[key] = value
    return tuple(entries.items())


async def read_frame(channel, *, max_frame_bytes: int) -> Frame:
    """Read one frame through BoundedChannel; EOF/cancellation propagate.

    max_frame_bytes includes the five-byte header. Unknown formats fail closed;
    the caller must let request_stream close the failed connection.
    """
    if type(max_frame_bytes) is not int or max_frame_bytes < 5:
        raise ValueError("Invalid frame byte limit")
    header = await channel.readexactly(5)
    kind = header[0] >> 4
    if header[0] & 15 or kind not in range(1, 7):
        raise FrameError("Unsupported frame kind or header flags")
    remaining = int.from_bytes(header[1:], "big")
    if remaining > max_frame_bytes - 5:
        raise FrameError("Frame exceeds byte limit")
    if kind == 1:
        if remaining:
            raise FrameError("Heartbeat must be empty")
        return Frame(1, None, None, 0, 0, (), None, b"")

    async def take(size):
        nonlocal remaining
        if size > remaining:
            raise FrameError("Metadata exceeds declared frame length")
        result = await channel.readexactly(size)
        remaining -= size
        return result

    sequence = None
    topic = None
    if kind in (3, 4, 5):
        sequence = int.from_bytes(await take(2), "big")
    elif kind == 6:
        length = int.from_bytes(await take(2), "big")
        try:
            topic = (await take(length)).decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FrameError("Invalid UTF-8 topic") from exc
    metadata = await take(5)
    command = int.from_bytes(metadata[:2], "big")
    flags = metadata[2]
    extensions = _extensions(await take(int.from_bytes(metadata[3:], "big")))
    body = await take(remaining)
    return Frame(kind, command, sequence, flags >> 3, flags & 7,
                 extensions, topic, body)
