from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from empire.contracts.plugin import PluginManifest

CHINA = timezone(timedelta(hours=8))
HISTORY_PER_TASK = 100


def retain_task_history(records):
    """Keep each task's newest records independently; this is Redis-only control data."""
    counts, retained = {}, []
    for record in sorted(records, key=lambda item: item["finished_at"], reverse=True):
        ident = record["task_id"]
        count = counts.get(ident, 0)
        if count < HISTORY_PER_TASK:
            retained.append(record)
            counts[ident] = count + 1
    return retained


@dataclass(frozen=True)
class CollectionTask:
    id: str
    name: str
    capability: str
    rate_group: str
    description: str
    interval_minutes: int = 1440


def validate_policy(value):
    result = dict(value)
    if result.get("mode") not in ("manual", "interval", "daily"):
        raise ValueError("请选择手动、固定间隔或每天执行")
    if type(result.get("interval_minutes")) is not int or not 1 <= result["interval_minutes"] <= 43200:
        raise ValueError("采集间隔须为 1～43200 分钟")
    try:
        datetime.strptime(result["daily_time"], "%H:%M")
    except (KeyError, ValueError, TypeError):
        raise ValueError("每日时间须为 HH:MM") from None
    if type(result.get("request_retries")) is not int or not 0 <= result["request_retries"] <= 5:
        raise ValueError("单次请求重试次数须为 0～5")
    if type(result.get("enabled")) is not bool:
        raise ValueError("任务开关无效")
    return {k: result[k] for k in ("mode", "interval_minutes", "daily_time", "request_retries", "enabled")}


def next_due(policy, now):
    if not policy["enabled"] or policy["mode"] == "manual":
        return None
    if policy["mode"] == "interval":
        return now + policy["interval_minutes"] * 60
    hour, minute = map(int, policy["daily_time"].split(":"))
    current = datetime.fromtimestamp(now, CHINA)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target.timestamp()


class CollectionControl:
    def __init__(self, definitions):
        self.definitions = {item.id: item for item in definitions}
        self.manifest = PluginManifest(
            "collection.control", "采集任务管理", requires=("redis.store", "http.fetch", "collection.records",
            *(item.capability for item in definitions)), provides=("collection.control",),
            description="统一执行计划、断点续采、网站频控和运行记录",
        )
        self.tasks = {}
        self.state = {}
        self.lock = asyncio.Lock()
        self.error = ""
        self.loop = None

    async def start(self, context):
        self.context = context
        store = context.get("redis.store")
        self.redis, self.key = store.client, f"{store.prefix}:collection:control:v1"
        self.http = context.get("http.fetch")
        self.records = context.get("collection.records")
        raw = await self.redis.get(self.key)
        self.state = json.loads(raw) if raw else {"jobs": {}, "history": []}
        for ident in self.definitions:
            self.state["jobs"].setdefault(ident, {
                "policy": {"enabled": True, "mode": "manual", "interval_minutes": self.definitions[ident].interval_minutes,
                           "daily_time": "18:00", "request_retries": 2},
                "next_due": None, "active": None, "last_status": "idle",
            })
            validate_policy(self.state["jobs"][ident]["policy"])
        await self._persist()
        self.loop = context.spawn(self._schedule(), name="collection-schedules")
        return {"collection.control": self}

    async def _persist(self):
        # One atomic Redis SET saves progress and bounded run history together.
        # Never publish operational history into the archival data stream.
        self.state["history"] = retain_task_history(self.state["history"])
        await self.redis.set(self.key, json.dumps(self.state, ensure_ascii=False))

    async def configure(self, ident, policy):
        policy = validate_policy(policy)
        async with self.lock:
            job = self.state["jobs"][ident]
            old = copy.deepcopy(job)
            job["policy"] = policy
            job["next_due"] = next_due(policy, time.time())
            try:
                await self._persist()
            except Exception:
                self.state["jobs"][ident] = old
                raise
        return "设置已保存；执行计划立即生效，请求重试策略在下次运行生效"

    async def run(self, ident, fresh=False, origin="manual"):
        async with self.lock:
            job = self.state["jobs"][ident]
            if not job["policy"]["enabled"]:
                raise ValueError("任务已禁用，请先启用并保存")
            if ident in self.tasks and not self.tasks[ident].done():
                raise ValueError("任务正在执行，不能重复启动")
            previous = copy.deepcopy(job)
            # An interrupted active record is reused, including its run identifier.
            active = job["active"]
            if not active:
                collector = self.context.get(self.definitions[ident].capability)
                baseline = await collector.checkpoint_revision()
                active = {"run_id": uuid4().hex, "task_id": ident,
                    "started_at": time.time(), "origin": origin, "fresh": fresh,
                    "baseline_revision": baseline}
            if job["active"] and fresh:
                raise ValueError("存在待恢复任务，请先停止后再重新采集")
            job.update(active=active, last_status="running")
            try:
                await self._persist()
            except Exception:
                self.state["jobs"][ident] = previous
                raise
            self.tasks[ident] = self.context.spawn(self._execute(ident), name=ident)
        return active["run_id"]

    async def _execute(self, ident):
        job = self.state["jobs"][ident]
        active = dict(job["active"])
        collector = self.context.get(self.definitions[ident].capability)
        status, error, result = "complete", "", {}
        try:
            collector.request_retries = job["policy"]["request_retries"]
            result = await collector.execute(fresh=active["fresh"],
                                             baseline_revision=active["baseline_revision"])
        except asyncio.CancelledError:
            status = "paused"
        except Exception as exc:
            status, error = "error", self.records.sanitize_text(exc)
        async with self.lock:
            job = self.state["jobs"][ident]
            job.update(active=None, last_status=status, error=error,
                       next_due=next_due(job["policy"], time.time()))
            self.state["history"].insert(0, {**active, "finished_at": time.time(),
                "status": status, "error": error, "result": result})
            await self._persist()

    async def pause(self, ident):
        # Pause the plan as well, so the next timer tick cannot restart it.
        policy = {**self.state["jobs"][ident]["policy"], "enabled": False}
        await self.configure(ident, policy)
        task = self.tasks.get(ident)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.lock:
            job = self.state["jobs"][ident]
            if job["active"]:
                self.state["history"].insert(0, {**job["active"], "finished_at": time.time(),
                    "status": "paused", "error": "", "result": {}})
                job.update(active=None, last_status="paused")
                await self._persist()
        return "任务与执行计划已暂停，采集断点保留"

    async def _schedule(self):
        while True:
            try:
                for ident, job in self.state["jobs"].items():
                    if ident not in self.definitions or not job["policy"]["enabled"]:
                        continue
                    if ident in self.tasks and not self.tasks[ident].done():
                        continue
                    if job["active"] or (job["next_due"] and job["next_due"] <= time.time()):
                        await self.run(ident, origin="schedule")
                self.error = ""
            except Exception as exc:
                self.error = self.records.sanitize_text(exc)
            await asyncio.sleep(1)

    async def snapshot(self):
        return {"jobs": [{**copy.deepcopy(self.state["jobs"][ident]),
            "id": ident, "name": spec.name, "description": spec.description,
            "rate_group": spec.rate_group,
            "progress": self.context.get(spec.capability).health()}
            for ident, spec in self.definitions.items()],
            "history": copy.deepcopy(self.state["history"]),
            "sites": await self.http.settings(), "error": self.error}

    async def configure_site(self, name, interval_ms):
        return await self.http.configure_interval(name, interval_ms)

    async def stop(self):
        if self.loop:
            self.loop.cancel()
            await asyncio.gather(self.loop, return_exceptions=True)
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def health(self):
        return {"tasks": len(self.definitions), "running": sum(not t.done() for t in self.tasks.values()),
                "error": self.error}
