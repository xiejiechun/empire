"""Bounded operational counters, in memory only; never business write evidence."""
from bisect import bisect_left
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic, perf_counter

PHASES = frozenset({'read', 'normalize', 'plan', 'hash', 'cache_read', 'sql', 'cache_write', 'ack'})
BOUNDS_MS = (.1, .5, 1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 5000, float('inf'))


class StageWindow:
    """At most 300 one-second histogram buckets, no per-message history."""
    def __init__(self):
        self.buckets = deque()

    def expire(self, tick):
        while self.buckets and self.buckets[0][0] <= tick - 300:
            self.buckets.popleft()

    def add(self, seconds, tick):
        self.expire(tick)
        if not self.buckets or self.buckets[-1][0] != tick:
            self.buckets.append([tick, 0, 0.0, 0.0, [0] * len(BOUNDS_MS)])
        row = self.buckets[-1]
        milliseconds = max(0.0, seconds * 1000)
        row[1] += 1
        row[2] += milliseconds
        row[3] = max(row[3], milliseconds)
        row[4][bisect_left(BOUNDS_MS, milliseconds)] += 1

    def snapshot(self, tick, seconds):
        self.expire(tick)
        selected = [row for row in self.buckets if row[0] > tick - seconds]
        count = sum(row[1] for row in selected)
        histogram = [sum(row[4][i] for row in selected) for i in range(len(BOUNDS_MS))]
        maximum = max((row[3] for row in selected), default=0)
        result = dict(count=count, total_ms=sum(row[2] for row in selected), max_ms=maximum)
        for name, fraction in (('p50_upper_ms', .5), ('p95_upper_ms', .95), ('p99_upper_ms', .99)):
            cumulative = 0
            result[name] = None
            for boundary, number in zip(BOUNDS_MS, histogram):
                cumulative += number
                if count and cumulative >= count * fraction:
                    result[name] = min(boundary, maximum)
                    break
        return result


class ArchiveMetrics:
    def __init__(self):
        self.since = datetime.now(UTC).isoformat()
        self.projects = {}
        self.timings = {}
        self.timing_enabled = True

    def reset(self, projects):
        self.since = datetime.now(UTC).isoformat()
        self.projects = {project: dict(checked=0, equal=0, stale=0, changed=0,
            missing=0, sql_attempts=0, sql_successes=0, written=0,
            acknowledged=0, deleted=0) for project in projects}
        self.timings = {}

    @contextmanager
    def span(self, project, phase):
        if not self.timing_enabled or project not in self.projects or phase not in PHASES:
            yield
            return
        began = perf_counter()
        try:
            yield
        finally:
            stages = self.timings.setdefault(project, {})
            stages.setdefault(phase, StageWindow()).add(perf_counter() - began, int(monotonic()))

    def add(self, project, **counts):
        # Unknown envelope IDs cannot grow telemetry storage.
        row = self.projects.get(project)
        if row is not None:
            for key, count in counts.items():
                row[key] += count

    def snapshot(self, project):
        row = self.projects.get(project)
        if row is None:
            return None
        tick = int(monotonic())
        timings = {phase: {f'{seconds}s': window.snapshot(tick, seconds) for seconds in (10, 300)}
                   for phase, window in self.timings.get(project, {}).items()}
        return dict(since=self.since, **row, timings=timings)
