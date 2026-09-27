"""Disposable Stream-ID index and round-robin admission, never business storage."""
from collections import OrderedDict
from dataclasses import dataclass, field
from time import monotonic

from empire.core.identity import safe_project_id

TAIL_ID = """
if redis.call('EXISTS', KEYS[1]) == 0 then return false end
local info = redis.call('XINFO', 'STREAM', KEYS[1])
for i = 1, #info, 2 do
    if info[i] == 'last-generated-id' then return info[i+1] end
end
return false
"""

# Bound the returned payload before Redis sends it to Python. No writes/ACK here.
SCAN_WINDOW = """
local rows = redis.call('XRANGE', KEYS[1], ARGV[1], ARGV[2], 'COUNT', ARGV[3])
local result, bytes = {}, 0
for _, row in ipairs(rows) do
    local size = #row[1]
    for _, value in ipairs(row[2]) do size = size + #value end
    if bytes + size > tonumber(ARGV[4]) then
        return {result, bytes, row[1], size}
    end
    result[#result+1] = row
    bytes = bytes + size
end
return {result, bytes, '', 0}
"""


@dataclass(frozen=True)
class ArchiveLimits:
    batch_size: int = 100
    scan_max_messages: int = 500
    scan_max_bytes: int = 8 * 1024 * 1024
    scan_time_ms: int = 50
    work_max_units: int = 32
    work_time_ms: int = 50
    index_max_entries: int = 100000

    @classmethod
    def from_settings(cls, settings):
        values = {}
        for name, maximum in (("batch_size", 100), ("scan_max_messages", 100000),
                              ("scan_max_bytes", 256 * 1024 * 1024), ("scan_time_ms", 5000),
                              ("work_max_units", 10000), ("work_time_ms", 5000),
                              ("index_max_entries", 1000000)):
            value = settings.get(name, getattr(cls, name))
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"archive.{name} 须为 1～{maximum} 的整数")
            values[name] = value
        return cls(**values)


@dataclass(eq=False)
class Batch:
    key: tuple
    project: str
    incremental: bool
    ids: dict = field(default_factory=dict)
    complete: bool = False
    checked: bool = False
    dirty: bool = True


class ArchiveIndexFull(RuntimeError):
    pass


class ArchiveQueue:
    def __init__(self, limit):
        self.limit = limit
        self.batches = {}
        self.projects = {}
        self.dirty = set()
        self.ids = {}
        self.ready = OrderedDict()
        self.delayed = {}
        self.cursor = "0-0"
        self.cutoff = None
        self.stable_cutoff = "0-0"
        self.more_scan = False
        self.next_recheck = monotonic() + 60

    def add(self, ident, envelope, incremental, project=None, complete=None):
        if ident in self.ids:
            return
        if len(self.ids) >= self.limit:
            raise ArchiveIndexFull("归档消息索引达到容量上限；消息保留，请检查积压或调整 index_max_entries")
        key = (envelope.source, envelope.job_key, envelope.batch_id)
        batch = self.batches.get(key)
        if batch is None:
            project = project or safe_project_id(envelope.job_key or envelope.source)
            batch = self.batches[key] = Batch(key, project, incremental)
            # A fresh batch can supersede a parked incomplete one, but only after
            # the scanner's full cutoff fence and the checkpoint check agree.
            for previous in self.projects.get(project, ()):
                if not previous.incremental:
                    previous.checked = False
                    previous.dirty = True
                    self.dirty.add(previous)
            self.projects.setdefault(project, set()).add(batch)
        batch.ids[ident] = None
        self.ids[ident] = batch
        batch.dirty = True
        self.dirty.add(batch)
        batch.complete |= envelope.dataset.endswith(".complete") if complete is None else complete
        if incremental:
            self.schedule(batch)

    def schedule(self, batch):
        if batch.ids:
            self.ready.setdefault(batch.project, OrderedDict())[batch.key] = batch

    def finish_scan(self):
        self.stable_cutoff = self.cutoff
        self.cutoff = None
        self.more_scan = False
        for batch in self.dirty:
            if batch.dirty and (batch.complete or not batch.checked):
                self.schedule(batch)
            batch.dirty = False
        self.dirty.clear()

    def recheck(self, *, retry_failed):
        clock = monotonic()
        for project, (deadline, batches) in list(self.delayed.items()):
            if retry_failed or clock >= deadline:
                self.delayed.pop(project)
                for batch in batches.values():
                    self.schedule(batch)
        if clock >= self.next_recheck and self.cutoff is None:
            for batch in self.batches.values():
                if not batch.incremental:
                    self.schedule(batch)
            self.next_recheck = clock + 60

    def take(self, excluded=()):
        for _ in range(len(self.ready)):
            project, batches = self.ready.popitem(last=False)
            if project in excluded:
                self.ready[project] = batches
                continue
            if project in self.delayed:
                self.delayed[project][1].update(batches)
                continue
            _, batch = batches.popitem(last=False)
            if batches:
                self.ready[project] = batches
            if not batch.incremental and self.cutoff is not None:
                self.schedule(batch)
                continue
            return batch
        return None

    def reschedule(self, batch, *, failed=False):
        if failed:
            pending = OrderedDict([(batch.key, batch)])
            pending.update(self.ready.pop(batch.project, {}))
            self.delayed[batch.project] = (monotonic() + 5, pending)
        elif batch.incremental and batch.ids:
            self.schedule(batch)

    def forget(self, ids):
        for ident in ids:
            batch = self.ids.pop(ident, None)
            if batch is None:
                continue
            batch.ids.pop(ident, None)
            if not batch.ids:
                self.batches.pop(batch.key, None)
                self.dirty.discard(batch)
                project = self.projects[batch.project]
                project.discard(batch)
                if not project:
                    self.projects.pop(batch.project)
                ready = self.ready.get(batch.project)
                if ready is not None:
                    ready.pop(batch.key, None)
                    if not ready:
                        self.ready.pop(batch.project)

    def wait_seconds(self, excluded=()):
        if self.more_scan or any(p not in self.delayed and p not in excluded for p in self.ready):
            return .01
        if self.delayed:
            return max(.01, min(deadline for deadline, _ in self.delayed.values()) - monotonic())
        return 60


def stream_number(value):
    return tuple(map(int, value.split("-")))
