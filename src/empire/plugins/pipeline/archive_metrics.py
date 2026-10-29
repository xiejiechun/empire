"""Bounded operational counters, in memory only; never business write evidence."""
from datetime import UTC, datetime


class ArchiveMetrics:
    def __init__(self):
        self.since = datetime.now(UTC).isoformat()
        self.projects = {}

    def reset(self, projects):
        self.since = datetime.now(UTC).isoformat()
        self.projects = {project: dict(checked=0, equal=0, stale=0, changed=0,
            missing=0, sql_attempts=0, sql_successes=0, written=0) for project in projects}

    def add(self, project, **counts):
        # Unknown envelope IDs cannot grow telemetry storage.
        row = self.projects.get(project)
        if row is not None:
            for key, count in counts.items():
                row[key] += count

    def snapshot(self, project):
        row = self.projects.get(project)
        return dict(since=self.since, **row) if row is not None else None
