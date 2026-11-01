"""One process-wide authentication generation per durable node profile."""
import asyncio
from dataclasses import dataclass

from empire.sources.yuanhang_auth import AuthenticationError


@dataclass(repr=False)
class SessionEntry:
    profile: object
    session: object
    refreshed: bool = False
    blocked: bool = False


class NodeSessions:
    def __init__(self):
        self.entries = {}
        # Fixed stripes prevent lock growth from arbitrary missing node names.
        self.locks = [asyncio.Lock() for _ in range(64)]
        self.stats = dict(logins=0, hits=0, refreshes=0, blocked=0)

    async def get(self, code, profile, authenticate, *, rejected=None):
        async with self.locks[hash(code) % len(self.locks)]:
            entry = self.entries.get(code)
            if entry is not None and entry.profile != profile:
                self.entries.pop(code)
                entry = None
            refresh = entry is not None and rejected is entry.session
            if entry is not None:
                if entry.blocked or (refresh and entry.refreshed):
                    self.reject(code, entry.session)
                    raise AuthenticationError('session-rejected-after-refresh')
                if not refresh:
                    self.stats['hits'] += 1
                    return entry.session
            if refresh:
                # Failed refresh must not cause a login storm from waiting callers.
                entry.blocked = True
                self.stats['refreshes'] += 1
            session = await authenticate()
            self.stats['logins'] += 1
            self.entries[code] = SessionEntry(profile, session, refreshed=refresh)
            return session

    def confirm(self, code, session):
        entry = self.entries.get(code)
        if entry is not None and entry.session is session and not entry.blocked:
            entry.refreshed = False

    def reject(self, code, session):
        entry = self.entries.get(code)
        if entry is not None and entry.session is session and not entry.blocked:
            entry.blocked = True
            self.stats['blocked'] += 1

    def prune(self, profiles):
        for code, entry in list(self.entries.items()):
            if profiles.get(code) != entry.profile:
                self.entries.pop(code)
