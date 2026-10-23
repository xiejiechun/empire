import asyncio

import pytest

from empire.features.themes.socket_frame import FrameError, read_frame


def packet(kind=2, body=b"example", *, prefix=b"", flags=0, extensions=b""):
    payload = prefix + b"\x0b\xc1" + bytes([flags])
    payload += len(extensions).to_bytes(2, "big") + extensions + body
    return bytes([kind << 4]) + len(payload).to_bytes(4, "big") + payload


async def parse(data, limit=4096):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return await read_frame(reader, max_frame_bytes=limit)


@pytest.mark.asyncio
async def test_coalesced_frames_do_not_consume_next_response():
    reader = asyncio.StreamReader()
    data = packet(body=b"one")
    reader.feed_data(data + packet(body=b"two"))
    reader.feed_eof()
    first = await read_frame(reader, max_frame_bytes=len(data))
    assert first.command == 3009
    assert first.plaintext() == b"one"
    assert (await read_frame(reader, max_frame_bytes=4096)).plaintext() == b"two"


@pytest.mark.asyncio
async def test_fragmentation_waits_for_entire_body():
    reader = asyncio.StreamReader()
    task = asyncio.create_task(read_frame(reader, max_frame_bytes=4096))
    data = packet()
    for value in data[:-1]:
        reader.feed_data(bytes([value]))
        await asyncio.sleep(0)
        assert not task.done()
    reader.feed_data(data[-1:])
    assert (await task).plaintext() == b"example"


@pytest.mark.asyncio
@pytest.mark.parametrize("cut", range(17))
async def test_truncation_never_returns_partial_frame(cut):
    with pytest.raises(asyncio.IncompleteReadError):
        await parse(packet()[:cut])


@pytest.mark.asyncio
async def test_sequence_extensions_and_topic():
    ext = b"\x01" + (123).to_bytes(8, "big") + b"\x02\x00\x09\x03\x00\x02ok"
    frame = await parse(packet(3, prefix=b"\x00\x07", extensions=ext))
    assert frame.sequence == 7
    assert frame.extensions == ((1, 123), (2, 9), (3, "ok"))
    frame = await parse(packet(6, prefix=b"\x00\x03abc"))
    assert frame.topic == "abc"
    with pytest.raises(FrameError):
        frame.plaintext()


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", [1, 2, 7, 8, 255])
async def test_encryption_and_status_cannot_be_read_as_plaintext(flags):
    frame = await parse(packet(flags=flags))
    with pytest.raises(FrameError):
        frame.plaintext()


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", [b"\x04\x00\x00\x00\x01", b"\x09", b"\x01",
                                     b"\x02\x00\x01\x02\x00\x02",
                                     b"\x03\x00\x01\xff"])
async def test_unsupported_or_malformed_extension(ext):
    with pytest.raises(FrameError):
        await parse(packet(extensions=ext))


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"\x20\xff\xff\xff\xff", b"\x21\x00\x00\x00\x00",
    b"\x70\x00\x00\x00\x00", b"\x20\x00\x00\x00\x04abcd",
    b"\x10\x00\x00\x00\x01x"])
async def test_invalid_header_fails_without_body_allocation(data):
    with pytest.raises(FrameError):
        await parse(data)


@pytest.mark.asyncio
async def test_empty_heartbeat_not_catalog():
    frame = await parse(b"\x10\x00\x00\x00\x00")
    assert frame.kind == 1
    with pytest.raises(FrameError):
        frame.plaintext()
