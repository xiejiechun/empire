"""Bounded SOCKS5 / HTTP CONNECT handshakes for an already leased proxy route."""
import asyncio
import base64
import ssl
from urllib.parse import unquote, urlsplit


async def close_writer(writer):
    """Bound shutdown even when the peer or TLS shutdown never completes."""
    writer.close()
    try:
        async with asyncio.timeout(2):
            await writer.wait_closed()
    except (OSError, TimeoutError):
        pass
    finally:
        writer.transport.abort()


async def _socks(reader, writer, target_host, target_port, user, password):
    writer.write(b"\x05\x01\x02")
    await writer.drain()
    if await reader.readexactly(2) != b"\x05\x02":
        raise OSError("SOCKS5 authentication method rejected")
    login, secret = user.encode(), password.encode()
    if not 1 <= len(login) <= 255 or not 1 <= len(secret) <= 255:
        raise ValueError("SOCKS5 credential length invalid")
    writer.write(b"\x01" + bytes([len(login)]) + login + bytes([len(secret)]) + secret)
    await writer.drain()
    if await reader.readexactly(2) != b"\x01\x00":
        raise OSError("SOCKS5 authentication rejected")
    host = target_host.encode("idna")
    if not 1 <= len(host) <= 255:
        raise ValueError("SOCKS5 destination length invalid")
    writer.write(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + target_port.to_bytes(2, "big"))
    await writer.drain()
    head = await reader.readexactly(4)
    if head[:3] != b"\x05\x00\x00":
        raise OSError("SOCKS5 destination connection rejected")
    if head[3] == 1:
        length = 4
    elif head[3] == 4:
        length = 16
    elif head[3] == 3:
        length = (await reader.readexactly(1))[0]
    else:
        raise OSError("SOCKS5 destination response invalid")
    await reader.readexactly(length + 2)


async def _connect(reader, writer, host, port, user, password):
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    writer.write((f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                  f"Proxy-Authorization: Basic {token}\r\n\r\n").encode("ascii"))
    await writer.drain()
    # Reader limit applies to handshake headers; never include response text in errors.
    header = await reader.readuntil(b"\r\n\r\n")
    if len(header) > 16384:
        raise OSError("Proxy CONNECT header too large")
    status = header.split(b"\r\n", 1)[0].split(b" ")
    if len(status) < 2 or status[0] not in (b"HTTP/1.0", b"HTTP/1.1") or status[1] != b"200":
        raise OSError("Proxy CONNECT rejected")


async def open_tunnel(proxy_url, host, port):
    """Keep credentials in infrastructure memory; callers receive streams only."""
    proxy = urlsplit(proxy_url)
    if proxy.scheme not in ("socks5", "socks5h", "http", "https"):
        raise ValueError("Unsupported proxy tunnel protocol")
    reader, writer = await asyncio.open_connection(
        proxy.hostname, proxy.port, limit=16384,
        ssl=ssl.create_default_context() if proxy.scheme == "https" else None,
    )
    try:
        user, password = unquote(proxy.username or ""), unquote(proxy.password or "")
        if proxy.scheme.startswith("socks5"):
            await _socks(reader, writer, host, port, user, password)
        else:
            await _connect(reader, writer, host, port, user, password)
        return reader, writer
    except BaseException:
        await close_writer(writer)
        raise
