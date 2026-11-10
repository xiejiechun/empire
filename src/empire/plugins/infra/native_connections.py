"""Bounded native keep-alive ownership inside the shared downloader."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic

from empire.plugins.infra.proxy_tunnel import close_writer


@dataclass(eq=False)
class Connection:
    reader: object
    writer: object
    entry: object
    state: dict = field(default_factory=dict)


class NativeConnections:
    def __init__(self, service):
        self.service = service
        self.idle = {}
        self.closing = set()
        self.stats = dict(opened=0, reused=0, closed=0)

    async def retire(self, connection):
        # Retain close ownership even if a requesting task is cancelled again.
        task = asyncio.create_task(close_writer(connection.writer))
        self.closing.add(task)
        task.add_done_callback(self.closing.discard)
        self.stats['closed'] += 1
        await asyncio.shield(task)

    async def prune(self):
        pool = self.service.pool
        for key, conn in list(self.idle.items()):
            entry = conn.entry
            stale = (conn.writer.is_closing() or conn.reader.at_eof()
                     or conn.reader.exception() is not None)
            if entry is not None:
                stale |= (pool.entries.get(entry.code) is not entry or entry.expires <= monotonic())
            if stale and self.idle.get(key) is conn:
                self.idle.pop(key)
                await self.retire(conn)

    @asynccontextmanager
    async def connection(self, target, entry, site, token, *, fresh=False):
        await self.prune()
        key = (target, id(entry), token)
        conn = self.idle.pop(key, None)
        if fresh and conn is not None:
            await self.retire(conn)
            conn = None
        # A changed session for the same route must not retain old credentials.
        for old_key in list(self.idle):
            if old_key[:2] == key[:2]:
                await self.retire(self.idle.pop(old_key))
        if conn is None:
            while len(self.idle) >= self.service.global_limit:
                await self.retire(self.idle.pop(next(iter(self.idle))))
            if entry is None:
                reader, writer = await asyncio.open_connection(target.host, target.port, limit=16384)
            else:
                reader, writer = await self.service.pool.open_tunnel(entry, target.host, target.port, site=site)
            conn = Connection(reader, writer, entry)
            self.stats['opened'] += 1
        else:
            self.stats['reused'] += 1
        try:
            yield conn
        except BaseException:
            await self.retire(conn)
            raise
        else:
            if self.service.closed or conn.writer.is_closing() or conn.reader.at_eof():
                await self.retire(conn)
            else:
                while len(self.idle) >= self.service.global_limit:
                    await self.retire(self.idle.pop(next(iter(self.idle))))
                self.idle[key] = conn

    async def close(self):
        while self.idle:
            await self.retire(self.idle.pop(next(iter(self.idle))))
        if self.closing:
            await asyncio.gather(*self.closing, return_exceptions=True)
