from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from empire.contracts.plugin import PluginManifest
from empire.core.identity import safe_project_id
from empire.core.time import CHINA
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore

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
class TaskContribution:
    id: str
    name: str
    capability: str
    rate_group: str
    description: str
    interval_seconds: int = 86400
    category: str = "其他"
    source_name: str = ""
    parallel_downloads: bool = False
    fresh_description: str = "创建新批次；已归档数据按对应业务规则保留。"


def validate_policy(value):
    result = dict(value)
    if result.get("mode") not in ("manual", "interval", "daily"):
        raise ValueError("请选择手动、固定间隔或每天执行")
    if "interval_minutes" in result or "interval_seconds" not in result:
        raise ValueError("采集间隔必须使用秒；旧配置请通过维护入口迁移")
    if type(result["interval_seconds"]) is not int or not 1 <= result["interval_seconds"] <= 2592000:
        raise ValueError("采集间隔须为 1～2592000 秒（最多 30 天）")
    try:
        datetime.strptime(result["daily_time"], "%H:%M")
    except (KeyError, ValueError, TypeError):
        raise ValueError("每日时间须为 HH:MM") from None
    if type(result.get("request_retries")) is not int or not 0 <= result["request_retries"] <= 5:
        raise ValueError("单次请求重试次数须为 0～5")
    if type(result.get("enabled")) is not bool:
        raise ValueError("任务开关无效")
    for field, default in (("use_proxy", False), ("proxy_fallback", True)):
        result.setdefault(field, default)
        if type(result[field]) is not bool:
            raise ValueError("代理采集开关无效")
    return {k: result[k] for k in ("mode", "interval_seconds", "daily_time", "request_retries", "enabled",
                                 "use_proxy", "proxy_fallback")}


def next_due(policy, now):
    if not policy["enabled"] or policy["mode"] == "manual":
        return None
    if policy["mode"] == "interval":
        return now + validate_policy(policy)["interval_seconds"]
    hour, minute = map(int, policy["daily_time"].split(":"))
    current = datetime.fromtimestamp(now, CHINA)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target.timestamp()


class CollectionControl:
    def __init__(self, definitions):
        definitions = tuple(definitions)
        self.definitions = {item.id: item for item in definitions}
        if len(self.definitions) != len(definitions):
            raise ValueError("采集任务贡献 ID 重复")
        for item in definitions:
            if safe_project_id(item.id) != item.id or not item.capability:
                raise ValueError("采集任务贡献身份无效")
        self.manifest = PluginManifest(
            "collection.control", "采集任务管理",
            requires=("redis.store", "mysql.store", "http.fetch", "collection.records"),
            provides=("collection.control",),
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
        self.settings = SettingsStore(context.get("mysql.store"), store.prefix)
        policies = await self.settings.load("task")
        raw = await self.redis.get(self.key)
        self.state = json.loads(raw) if raw else {"jobs": {}, "history": []}
        for ident in self.definitions:
            self.state["jobs"].setdefault(ident, {
                "policy": {"enabled": True, "mode": "manual", "interval_seconds": self.definitions[ident].interval_seconds,
                           "daily_time": "18:00", "request_retries": 2},
                "next_due": None, "active": None, "last_status": "idle",
            })
            job = self.state["jobs"][ident]
            cached = validate_policy(job["policy"])
            policy = validate_policy(policies.get(ident, {
                "enabled": True, "mode": "manual",
                "interval_seconds": self.definitions[ident].interval_seconds,
                "daily_time": "18:00", "request_retries": 2}))
            job["policy"] = policy
            if cached != policy or (job["next_due"] is None and not job["active"]):
                job["next_due"] = next_due(policy, time.time())
        await self._persist()
        self.loop = context.spawn(self._schedule(), name="collection-schedules", critical=True)
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
            await self.settings.save("task", ident, policy)
            job["policy"] = policy
            job["next_due"] = next_due(policy, time.time())
            try:
                await self._persist()
            except Exception:
                return "设置已保存到 MySQL 并生效；Redis 运行状态同步失败，重启后将按已保存配置重建计划"
        return "设置已保存到 MySQL；执行计划立即生效，重试和代理策略在下次运行生效"

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
                collector = self.context.optional(self.definitions[ident].capability)
                if collector is None:
                    raise ValueError("该采集插件当前未启用，请先在插件管理中启用")
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
        collector = self.context.optional(self.definitions[ident].capability)
        if collector is None:
            status, error = "unavailable", "采集插件在任务开始前已停用"
            async with self.lock:
                job.update(active=None, last_status=status, error=error,
                           next_due=next_due(job["policy"], time.time()))
                self.state["history"].insert(0, {**active, "finished_at": time.time(),
                    "status": status, "error": error, "result": {}})
                await self._persist()
            return
        status, error, result = "complete", "", {}
        proxy_token = USE_PROXY.set(job["policy"].get("use_proxy", False))
        fallback_token = PROXY_FALLBACK.set(job["policy"].get("proxy_fallback", True))
        network_counts = {}
        counts_token = ROUTE_COUNTS.set(network_counts)
        active["use_proxy"] = USE_PROXY.get()
        active["proxy_fallback"] = PROXY_FALLBACK.get()
        try:
            collector.request_retries = job["policy"]["request_retries"]
            result = await collector.execute(fresh=active["fresh"],
                                             baseline_revision=active["baseline_revision"])
        except asyncio.CancelledError:
            status = "paused"
        except Exception as exc:
            status, error = "error", self.records.sanitize_text(exc)
        finally:
            USE_PROXY.reset(proxy_token)
            PROXY_FALLBACK.reset(fallback_token)
            ROUTE_COUNTS.reset(counts_token)
        active["network"] = network_counts
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
                    if (ident not in self.definitions or not job["policy"]["enabled"]
                            or self.context.optional(self.definitions[ident].capability) is None):
                        continue
                    if ident in self.tasks and not self.tasks[ident].done():
                        continue
                    if job["active"] or (job["next_due"] and job["next_due"] <= time.time()):
                        await self.run(ident, origin="schedule")
                self.error = ""
            except Exception as exc:
                self.error = self.records.sanitize_text(exc)
            await asyncio.sleep(1)

    async def workspace(self, section="tasks", query="", category="", source="",
                        status="", offset=0, limit=25, project="", focus_task_id=""):
        """Bounded desktop projection; do not copy all run history on every refresh."""
        if section not in ("tasks", "sites", "history", "overview"):
            raise ValueError("未知工作区")
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError("分页范围无效")
        query = query.strip().casefold()
        if len(query) > 100:
            raise ValueError("搜索最多 100 字")
        if not isinstance(focus_task_id, str) or len(focus_task_id) > 100:
            raise ValueError("定位任务 ID 无效")
        specs = list(self.definitions.values())
        projects = [{"id": d.id, "name": d.name} for d in specs]
        counts = {"total": len(specs), "running": 0, "error": 0, "disabled": 0}
        candidates = []
        for spec in specs:
            job = self.state["jobs"][spec.id]
            state = "running" if job["active"] else (
                "disabled" if not job["policy"]["enabled"] else job["last_status"])
            if state in counts:
                counts[state] += 1
            if (query and query not in " ".join((spec.id, spec.name, spec.description,
                                                 spec.source_name, spec.rate_group)).casefold()):
                continue
            if category and spec.category != category:
                continue
            if source and spec.rate_group != source:
                continue
            if status and state != status:
                continue
            candidates.append(spec)
        base = {"jobs": [], "sites": [], "history": [], "projects": projects,
                "counts": counts, "error": self.error,
                "categories": sorted({d.category for d in specs}),
                "sources": sorted({d.rate_group for d in specs})}
        if section == "overview":
            base["history"] = copy.deepcopy(self.state["history"][:5])
            return base
        if section == "history":
            records = [h for h in self.state["history"]
                       if (not project or h["task_id"] == project)
                       and (not status or h["status"] == status)]
            total = len(records)
            offset = min(offset, max(0, (total - 1) // limit * limit))
            base.update(history=copy.deepcopy(records[offset:offset + limit]),
                        total=total, offset=offset, limit=limit)
            return base
        if section == "sites":
            sites = [s for s in await self.http.settings()
                     if not query or query in (s["name"] + " ".join(s["domains"])).casefold()]
            total = len(sites)
            offset = min(offset, max(0, (total - 1) // limit * limit))
            for site in sites[offset:offset + limit]:
                associated = [d.name for d in specs if d.rate_group == site["name"]]
                site["task_count"] = len(associated)
                site["task_names"] = associated[:5]
                base["sites"].append(site)
            base.update(total=total, offset=offset, limit=limit)
            return base
        if focus_task_id:
            focused = self.definitions.get(focus_task_id)
            candidates = [focused] if focused is not None else []
            base["focused_task_id"] = focus_task_id
            base["focus_missing"] = focused is None
        total = len(candidates)
        offset = min(offset, max(0, (total - 1) // limit * limit))
        page = candidates[offset:offset + limit]
        site_limits = {site["name"]: site for site in await self.http.settings()}
        for spec in page:
            base["jobs"].append({**copy.deepcopy(self.state["jobs"][spec.id]),
                "id": spec.id, "name": spec.name, "description": spec.description,
                "rate_group": spec.rate_group, "category": spec.category,
                "source_name": spec.source_name or spec.rate_group,
                "parallel_downloads": spec.parallel_downloads,
                "fresh_description": spec.fresh_description,
                "network_capacity": site_limits.get(spec.rate_group, {}),
                "progress": (self.context.optional(spec.capability).health()
                             if self.context.optional(spec.capability) else {"status": "unavailable"})})
        pending = {d.id for d in page}
        for record in self.state["history"]:
            if record["task_id"] in pending:
                base["history"].append(copy.deepcopy(record))
                pending.remove(record["task_id"])
            if not pending:
                break
        base.update(total=total, offset=offset, limit=limit)
        return base

    async def configure_site(self, name, values):
        if not isinstance(values, dict):
            raise ValueError("网站访问规则必须使用完整策略")
        return await self.http.configure_site(name, values)

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
