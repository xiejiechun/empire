"""Length-framed, bounded JSON transport, independent of Qt and business services."""
import json

MAX_FRAME = 2 * 1024 * 1024


def read_frame(stream):
    header = stream.readline(128)
    if not header:
        return None
    if not header.startswith(b'Content-Length: ') or not header.endswith(b'\r\n'):
        raise ValueError('Invalid protocol header')
    raw_length = header[16:-2]
    if not raw_length.isdigit():
        raise ValueError('Invalid protocol length')
    size = int(raw_length)
    if not 0 < size <= MAX_FRAME or stream.read(2) != b'\r\n':
        raise ValueError('Protocol frame exceeds limit or has invalid separator')
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError('Incomplete protocol frame')
        chunks.append(chunk)
        remaining -= len(chunk)
    value = json.loads(b''.join(chunks).decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Protocol request must be an object')
    return value


def encode_frame(value):
    body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(body) > MAX_FRAME:
        raise ValueError('Result exceeds frame limit; use pagination')
    return f'Content-Length: {len(body)}\r\n\r\n'.encode() + body
