"""Scheduling identity, bounds and fairness without service dependencies."""
from types import SimpleNamespace

import pytest

from empire.plugins.pipeline.archive_queue import ArchiveLimits, ArchiveQueue


def event(project, batch="batch", dataset="news.flash.page"):
    return SimpleNamespace(source="test", job_key=project, batch_id=batch, dataset=dataset)


@pytest.mark.parametrize("field", list(ArchiveLimits.__dataclass_fields__))
@pytest.mark.parametrize("value", [0, -1, True, "100", 1.5, float("inf")])
def test_limits_reject_invalid_types_and_ranges(field, value):
    with pytest.raises(ValueError):
        ArchiveLimits.from_settings({field: value})


def test_round_robin_keeps_next_project_across_one_unit_quanta():
    queue = ArchiveQueue(100)
    for i in range(20):
        queue.add(f"1-{i}", event("large"), True)
    for project in ("news", "calendar"):
        queue.add(f"2-{len(queue.ids)}", event(project), True)
    seen = []
    for _ in range(3):
        batch = queue.take()
        seen.append(batch.project)
        queue.forget([next(iter(batch.ids))])
        queue.reschedule(batch)
    assert seen == ["large", "news", "calendar"]
    assert len(queue.ids) == 19


def test_index_only_contains_bounded_ids_and_removes_empty_projects():
    queue = ArchiveQueue(1)
    queue.add("1-0", event("a"), True)
    with pytest.raises(RuntimeError, match="容量"):
        queue.add("2-0", event("b"), True)
    assert len(queue.ids) == 1
    queue.forget(["1-0"])
    assert not queue.ids and not queue.batches and not queue.projects and not queue.dirty
    queue.add("2-0", event("b"), True)
    assert queue.take().project == "b"


def test_stock_requires_complete_scan_fence_and_parked_batch_is_not_requeued():
    queue = ArchiveQueue(100)
    queue.cutoff = "2-0"
    queue.add("1-0", event("stocks", dataset="stock.universe.page"), False)
    assert queue.take() is None
    queue.cursor = "2-0"
    queue.finish_scan()
    batch = queue.take()
    batch.checked = True
    queue.reschedule(batch)
    assert queue.take() is None
    queue.cutoff = "3-0"
    queue.add("3-0", event("stocks", dataset="stock.universe.page"), False)
    queue.finish_scan()
    assert queue.take() is None  # Another page is not a reason to reread all partial pages.
    queue.cutoff = "4-0"
    queue.add("4-0", event("stocks", dataset="stock.universe.complete"), False)
    queue.finish_scan()
    assert queue.take() is batch


def test_failed_project_is_delayed_while_other_projects_continue(monkeypatch):
    monkeypatch.setattr("empire.plugins.pipeline.archive_queue.monotonic", lambda: 100)
    queue = ArchiveQueue(10)
    queue.add("1-0", event("bad"), True)
    queue.add("2-0", event("good"), True)
    bad = queue.take()
    queue.reschedule(bad, failed=True)
    assert queue.take().project == "good"
    assert queue.take() is None
    queue.recheck(retry_failed=False)
    assert queue.take() is None
    queue.recheck(retry_failed=True)
    assert queue.take() is bad
