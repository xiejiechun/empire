"""One streaming reader for buffered JSON and disk-backed large artifacts."""
import asyncio
import hashlib
import zlib

import httpx

from empire.contracts.download import CHUNK_BYTES, FilePolicy
from empire.plugins.infra.http_safety import SENSITIVE_HEADERS


class DownloadLimitError(ValueError):
    """Resource/format failure, not a failed proxy or a retryable transport error."""

    def __init__(self, message, *, sample=b"", observed_bytes=0, status_code=None):
        super().__init__(message)
        self.sample = sample
        self.observed_bytes = observed_bytes
        self.status_code = status_code


class ManagedResponse(httpx.Response):
    """The caller owns the buffer until close(), including ordered prefetch waits."""

    def __init__(self, original, content, *, artifact=None):
        self.managed_ready = False
        headers = original.headers.copy()
        headers.pop("content-encoding", None)
        headers["content-length"] = str(len(content))
        super().__init__(original.status_code, headers=headers, content=content,
                         request=original.request)
        self.artifact = artifact
        self.reservation = None
        self.on_close = None
        self.managed_ready = True

    def close(self):
        super().close()
        if not self.managed_ready:
            return
        self._content = b""
        self.stream = httpx.ByteStream(b"")
        self.__dict__.pop("_text", None)
        if self.reservation:
            self.reservation.release()
            self.reservation = None
        if self.on_close:
            callback, self.on_close = self.on_close, None
            callback(self)

    async def aclose(self):
        self.close()


async def disk_call(operation, *args, finish_on_cancel=False, cancel_cleanup=None):
    """Cancellation waits for the actual disk operation before cleanup owns its file."""
    future = asyncio.create_task(asyncio.to_thread(operation, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            cancelled = True  # Repeated cancellation must not cancel the thread wrapper.
        except Exception:
            if cancelled and not finish_on_cancel:
                raise asyncio.CancelledError from None
            raise
    if cancelled and not finish_on_cancel:
        if cancel_cleanup is not None:
            await disk_call(cancel_cleanup, result, finish_on_cancel=True)
        raise asyncio.CancelledError
    return result


async def read_response(client, method, url, *, policy, storage, on_headers,
                        strip_credentials=False, **kwargs):
    # httpx's automatic decompressor can allocate before aiter_bytes chunks output.
    # Read encoded bytes instead and bound each decompressor output allocation.
    headers = dict(kwargs.pop("headers", {}) or {})
    if not any(key.lower() == "accept-encoding" for key in headers):
        headers["Accept-Encoding"] = "gzip, deflate, identity"
    auth = kwargs.pop("auth", httpx.USE_CLIENT_DEFAULT)
    request = client.build_request(method, url, headers=headers, **kwargs)
    if strip_credentials:
        auth = None
        for name in SENSITIVE_HEADERS:
            request.headers.pop(name, None)
        # Ignore a manually configured default Host after crossing origins.
        request.headers["Host"] = httpx.Request(method, url).headers["Host"]
    response = await client.send(request, stream=True, auth=auth, follow_redirects=False)
    sink = None
    wire_count = body_count = 0
    prefix, body = bytearray(), bytearray()
    sha = hashlib.sha256()
    try:
        await on_headers(response)
        # Redirect bodies are irrelevant; closing the stream avoids unbounded junk.
        if response.status_code in (301, 302, 303, 307, 308, 204, 304) or method.upper() == "HEAD":
            return ManagedResponse(response, b"")
        file_mode = isinstance(policy, FilePolicy) and response.status_code == 200
        if isinstance(policy, FilePolicy) and response.status_code == 206:
            raise DownloadLimitError("文件下载不接受未经声明的部分响应")
        body_limit = policy.max_body_bytes
        if isinstance(policy, FilePolicy) and not file_mode:
            body_limit = min(body_limit, CHUNK_BYTES)
        declared = response.headers.get("content-length")
        if declared is not None:
            if not declared.isdecimal():
                raise DownloadLimitError("HTTP Content-Length 无效")
            declared = int(declared)
            if declared > policy.max_wire_bytes and method.upper() != "HEAD":
                raise DownloadLimitError("响应声明长度超过传输字节上限")
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity", "gzip", "deflate"):
            raise DownloadLimitError("来源使用了未支持的响应压缩编码")
        decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding in ("gzip", "deflate") else None
        # Mock/in-process transports can supply already consumed content. Real
        # network responses always use the raw streaming/decompression path below.
        consumed = response.is_stream_consumed
        if consumed:
            decoder = None
        if file_mode:
            # Admission scans and the store lock also belong off the event loop.
            sink = await disk_call(storage.begin, policy, cancel_cleanup=storage.end)

        async def accept(chunk):
            nonlocal body_count
            body_count += len(chunk)
            prefix.extend(chunk[:max(0, CHUNK_BYTES - len(prefix))])
            if body_count > body_limit:
                raise DownloadLimitError("响应正文超过插件声明的字节上限")
            sha.update(chunk)
            if sink:
                await disk_call(sink.write, chunk)
            else:
                body.extend(chunk)

        async def encoded_chunks():
            if consumed:
                yield response.content
            else:
                async for block in response.aiter_raw():
                    yield block

        async for block in encoded_chunks():
            wire_count += len(block)
            if wire_count > policy.max_wire_bytes:
                raise DownloadLimitError("响应实际传输超过字节上限")
            for offset in range(0, len(block), CHUNK_BYTES):
                chunk = block[offset:offset + CHUNK_BYTES]
                if decoder is None:
                    await accept(chunk)
                    continue
                while chunk:
                    decoded = decoder.decompress(chunk, CHUNK_BYTES)
                    await accept(decoded)
                    if decoder.unused_data:
                        raise DownloadLimitError("压缩响应含额外成员或尾部数据")
                    chunk = decoder.unconsumed_tail
            await asyncio.sleep(0)
        if decoder and not decoder.eof:
            raise DownloadLimitError("压缩响应未完整结束")
        if (declared is not None and not consumed and method.upper() != "HEAD"
                and response.status_code not in (204, 304) and wire_count != declared):
            raise DownloadLimitError("响应实际长度与声明不一致，文件未发布")
        # Publishing is a commit point: once entered, return its successful artifact
        # even if cancellation arrives during fsync/link. Never orphan a valid file.
        artifact = await disk_call(sink.commit, finish_on_cancel=True) if sink else None
        result = ManagedResponse(response, bytes(body), artifact=artifact)
        result.extensions["download"] = {"wire_bytes": wire_count, "body_bytes": body_count,
                                         "sha256": sha.hexdigest()}
        return result
    except (DownloadLimitError, zlib.error, ValueError, OSError) as exc:
        if not isinstance(exc, DownloadLimitError):
            message = "压缩响应损坏，未推进采集断点" if isinstance(exc, zlib.error) else str(exc)
            exc = DownloadLimitError(message)
        exc.sample, exc.observed_bytes = bytes(prefix), body_count
        exc.status_code = response.status_code
        raise exc from None
    finally:
        body.clear()
        prefix.clear()
        # An exception traceback must not retain already released download buffers.
        block = chunk = decoded = b""
        decoder = None
        try:
            await response.aclose()
        finally:
            if sink:
                await disk_call(storage.end, sink)
