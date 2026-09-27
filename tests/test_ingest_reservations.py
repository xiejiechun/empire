import asyncio
from types import SimpleNamespace

import pytest

from empire.contracts.data import BackpressureError, StaleCheckpointError, make_envelope
from empire.plugins.pipeline.ingest import IngestPlugin


class MemoryRedis:
    def __init__(self, *, queued=0, used=1000, maximum=100000):
        self.queued = queued
        self.used = used
        self.maximum = maximum
        self.revision = 0
        self.stale = False

    async def info(self, section):
        assert section == "memory"
        return {"used_memory": self.used, "maxmemory": self.maximum}

    async def xlen(self, stream):
        return self.queued

    async def eval(self, script, keys, *args):
        if self.stale:
            return [0, self.revision]
        count = int(args[4])
        self.queued += count
        self.revision += 1
        return [1, self.revision]


def ingest_service(client, *, capacity=5, page_bytes=1024):
    service = IngestPlugin({"max_queue_entries": capacity, "max_page_bytes": page_bytes,
                            "low_watermark": .5, "high_watermark": .7})
    service.redis = SimpleNamespace(prefix="test", stream="test:archive", client=client)
    service.archive = SimpleNamespace(blocked=False, request_flush=lambda: None)
    service.catalog = SimpleNamespace(canonicalize=lambda event: event,
                                      project_id=lambda event: event.job_key)
    service.stats = {"status": "ok", "published": 0}
    return service


def event():
    return make_envelope(source="test", dataset="metric.page", business_key="1",
                         job_key="job", run_id="run", batch_id="batch",
                         payload={"page": 1, "value": 1})


async def test_project_isolation_blocks_reserved_publish_without_advancing_checkpoint():
    redis = MemoryRedis()
    service = ingest_service(redis)
    reservation = await service.reserve_batch("job", 2)
    service.archive.blocked_projects = {"job"}
    with pytest.raises(BackpressureError, match="本项目"):
        await service.publish_page([event()], job_key="job", expected_revision=0,
                                   cursor={}, reservation=reservation)
    assert redis.revision == redis.queued == 0
    assert reservation.remaining_entries == 2
    service.archive.blocked_projects = {"another-project"}
    await service.publish_page([event()], job_key="job", expected_revision=0,
                               cursor={}, reservation=reservation)
    assert redis.revision == redis.queued == 1


@pytest.mark.parametrize("reserved", [False, True])
@pytest.mark.parametrize("blocked", ["project", "global", "unrelated"])
async def test_publish_rechecks_isolation_after_lock_wait(reserved, blocked):
    redis = MemoryRedis()
    service = ingest_service(redis)
    reservation = await service.reserve_batch("job", 2) if reserved else None
    before_bytes = reservation.remaining_bytes if reserved else None
    async with service.capacity_lock:
        task = asyncio.create_task(service.publish_page([event()], job_key="job",
            expected_revision=0, cursor={"page": 1}, reservation=reservation))
        await asyncio.sleep(0)
        assert not task.done()
        service.archive.blocked = blocked == "global"
        service.archive.blocked_projects = {"job" if blocked == "project" else "other"}
    if blocked == "unrelated":
        result = await asyncio.wait_for(task, 1)
        assert result["revision"] == redis.revision == redis.queued == 1
    else:
        with pytest.raises(BackpressureError):
            await asyncio.wait_for(task, 1)
        assert redis.revision == redis.queued == service.stats["published"] == 0
        if reservation:
            assert reservation.remaining_entries == 2
            assert reservation.remaining_bytes == before_bytes
            assert not reservation.released


@pytest.mark.parametrize("blocked", ["project", "global", "unrelated"])
async def test_publish_rechecks_isolation_after_capacity_query(blocked):
    redis = MemoryRedis()
    service = ingest_service(redis)
    original = redis.xlen

    async def change_during_query(stream):
        await asyncio.sleep(0)
        service.archive.blocked = blocked == "global"
        service.archive.blocked_projects = {"job" if blocked == "project" else "other"}
        return await original(stream)

    redis.xlen = change_during_query
    if blocked == "unrelated":
        await service.publish_page([event()], job_key="job", expected_revision=0, cursor={})
        assert redis.revision == redis.queued == 1
    else:
        with pytest.raises(BackpressureError):
            await service.publish_page([event()], job_key="job", expected_revision=0, cursor={})
        assert redis.revision == redis.queued == service.stats["published"] == 0


@pytest.mark.parametrize("reserved", [False, True])
async def test_isolation_after_dispatch_does_not_reject_successful_commit(reserved):
    redis = MemoryRedis()
    service = ingest_service(redis)
    reservation = await service.reserve_batch("job", 2) if reserved else None
    original = redis.eval

    async def committed_reply(*args):
        result = await original(*args)
        service.archive.blocked = True
        service.archive.blocked_projects = {"job"}
        await asyncio.sleep(0)
        return result

    redis.eval = committed_reply
    result = await service.publish_page([event()], job_key="job", expected_revision=0,
                                       cursor={}, reservation=reservation)
    assert result["revision"] == redis.revision == redis.queued == service.stats["published"] == 1
    if reservation:
        assert reservation.remaining_entries == 1


async def test_batch_reservation_prevents_other_tasks_stealing_completion_slots():
    redis = MemoryRedis()
    service = ingest_service(redis)
    reservation = await service.reserve_batch("job", 4)
    with pytest.raises(BackpressureError, match="容量水位"):
        await service.ensure_capacity(2)
    await service.publish_page([event()], job_key="job", expected_revision=0,
                               cursor={"page": 1}, reservation=reservation)
    assert reservation.remaining_entries == 3
    assert service.health()["reserved_entries"] == 3
    await reservation.release()
    assert service.health()["reserved_entries"] == 0


async def test_failed_publish_does_not_consume_reservation_and_release_is_idempotent():
    redis = MemoryRedis()
    service = ingest_service(redis)
    reservation = await service.reserve_batch("job", 2)
    redis.stale = True
    with pytest.raises(StaleCheckpointError):
        await service.publish_page([event()], job_key="job", expected_revision=0,
                                   cursor={}, reservation=reservation)
    assert reservation.remaining_entries == 2
    await reservation.release()
    await reservation.release()
    assert not service.reservations


async def test_same_job_cannot_hold_two_batch_reservations():
    service = ingest_service(MemoryRedis())
    reservation = await service.reserve_batch("job", 2)
    with pytest.raises(BackpressureError, match="已有整批入队预留"):
        await service.reserve_batch("job", 1)
    await reservation.release()


async def test_reservation_must_cover_incoming_entries():
    service = ingest_service(MemoryRedis())
    reservation = await service.reserve_batch("job", 1)
    with pytest.raises(BackpressureError, match="预留已失效"):
        await service.ensure_capacity(2, reservation)
    await reservation.release()


@pytest.mark.parametrize("queued,used,maximum,match", [
    (3, 1000, 100000, "消息槽"),
    (0, 6000, 10000, "最坏需要预留"),
])
async def test_impossible_batch_is_rejected_before_first_message(queued, used, maximum, match):
    service = ingest_service(MemoryRedis(queued=queued, used=used, maximum=maximum))
    with pytest.raises(BackpressureError, match=match):
        await service.reserve_batch("job", 3)
    assert service.health()["status"] == "paused"
    assert not service.reservations
