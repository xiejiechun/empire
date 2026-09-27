"""Deterministic, isolated capacity evidence for the production HTTP path.

This command never connects to RouterProxy, MySQL, Redis, or a public website.
It exercises the production proxy pool, routing, byte budget, and response reader
against an in-process directory and httpx MockTransport.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx

from empire.contracts.download import ResponsePolicy
from empire.plugins.infra.http import COOLDOWN_LUA, HttpService
from empire.plugins.infra.proxy_pool import CANDIDATE, DIRECTORY, ProxyPool
from empire.plugins.infra.routing import ROUTE_PERMIT, USE_PROXY

MIB = 1024 * 1024


def percentile(values: list[float], proportion: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * proportion
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def latency(values: list[float]) -> dict[str, float]:
    milliseconds = [value * 1000 for value in values]
    return {
        "p50_ms": round(percentile(milliseconds, .50), 3),
        "p95_ms": round(percentile(milliseconds, .95), 3),
        "max_ms": round(max(milliseconds, default=0), 3),
    }


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_resources() -> dict[str, int | None]:
    """Return current RSS and handle count without adding a runtime dependency."""
    if os.name == "nt":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessHandleCount.argtypes = [ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetProcessHandleCount.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(_ProcessMemoryCounters),
                                               ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        handles = ctypes.c_ulong()
        handle_ok = kernel32.GetProcessHandleCount(process, ctypes.byref(handles))
        return {
            "rss_bytes": int(counters.WorkingSetSize) if ok else None,
            "handles": int(handles.value) if handle_ok else None,
        }
    # The release gate is Windows-only. Keep developer runs portable where possible.
    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"rss_bytes": int(raw * (1 if sys.platform == "darwin" else 1024)),
                "handles": None}
    except ImportError:
        return {"rss_bytes": None, "handles": None}


class VirtualDirectory:
    """In-memory implementation of only the Redis scripts used by HTTP routing."""
    def __init__(self, devices: int, distinct_exits: int) -> None:
        self.mapping: dict[str, str] = {}
        self.expires: dict[str, float] = {}
        self.next_due: dict[str, float] = {}
        self.cooldowns: dict[str, float] = {}
        self.directory_reads = 0
        self.candidate_checks = 0
        for index in range(devices):
            self.put(index, distinct_exits)

    def put(self, index: int, distinct_exits: int, *, revision: int = 0) -> None:
        code = f"node{index:04}"
        exit_ip = str(ip_address(int(ip_address("198.18.0.1")) + index % distinct_exits))
        raw = json.dumps({"code": code,
                          "proxy": f"http://virtual:r{revision}@localhost:{31000 + index}",
                          "exit_ip": exit_ip}, separators=(",", ":"))
        old = self.mapping.get(code)
        if old is not None:
            self.expires.pop(old, None)
        self.mapping[code] = raw
        self.expires[raw] = time.monotonic() + 3600

    async def eval(self, script: str, count: int, *args: Any) -> Any:
        del count
        now_seconds = time.monotonic()
        now_ms = now_seconds * 1000
        if script == DIRECTORY:
            self.directory_reads += 1
            result: list[str] = []
            for code, raw in self.mapping.items():
                remaining = self.expires.get(raw, 0) - now_seconds
                if remaining > 0:
                    result.extend((code, raw, str(remaining)))
            return result
        if script == CANDIDATE:
            self.candidate_checks += 1
            code = str(args[-1])
            raw = self.mapping.get(code)
            remaining = self.expires.get(raw or "", 0) - now_seconds
            return [code, raw, str(remaining)] if raw and remaining > 0 else []
        if script == COOLDOWN_LUA:
            key, milliseconds = args
            self.cooldowns[str(key)] = max(self.cooldowns.get(str(key), 0),
                                           now_ms + int(milliseconds))
            return self.cooldowns[str(key)]
        if script != ROUTE_PERMIT:
            raise AssertionError("Capacity harness received an unknown Redis script")
        site, total, egress, total_ms, egress_ms, _direct = args
        wait = max(self.cooldowns.get(str(site), 0), self.next_due.get(str(total), 0),
                   self.next_due.get(str(egress), 0)) - now_ms
        if wait > 0:
            return max(1, int(wait))
        self.next_due[str(total)] = now_ms + int(total_ms)
        self.next_due[str(egress)] = now_ms + int(egress_ms)
        return 0


@dataclass
class ScenarioModel:
    name: str
    devices: int
    exits: int
    requests: int
    response_delay: float = .012
    fail_every: int = 0
    retry_failures: bool = False
    status_every: int = 0
    cancel_every: int = 0


async def measure_http(model: ScenarioModel) -> dict[str, Any]:
    directory = VirtualDirectory(model.devices, model.exits)
    started: dict[int, float] = {}
    transport_started: dict[int, float] = {}
    queue_times: list[float] = []
    download_times: list[float] = []
    parse_times: list[float] = []
    archive_queue_times: list[float] = []
    redis_confirm_times: list[float] = []
    sql_confirm_times: list[float] = []
    end_to_end: list[float] = []
    completed = failed = cancelled = active = peak = attempts = 0
    attempts_by_id: dict[int, int] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, attempts
        identifier = int(request.url.path.removeprefix("/item/"))
        attempts += 1
        attempts_by_id[identifier] = attempts_by_id.get(identifier, 0) + 1
        transport_started.setdefault(identifier, time.perf_counter())
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(model.response_delay)
            if (model.fail_every and identifier % model.fail_every == 0
                    and (not model.retry_failures or attempts_by_id[identifier] == 1)):
                raise httpx.ConnectError("deterministic virtual connection failure", request=request)
            status = 429 if model.status_every and identifier % model.status_every == 0 else 200
            headers = {"Retry-After": "1"} if status == 429 else {}
            return httpx.Response(status, headers=headers, content=b'{"ok":true}', request=request)
        finally:
            active -= 1

    def client_factory(_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)

    pool = ProxyPool(directory, client_factory=client_factory)
    service = HttpService(directory, "capacity", {
        "virtual": {"domains": ["capacity.invalid"], "scaling_mode": "auto",
                    "max_concurrency": 0, "proxy_interval_ms": 100,
                    "min_interval_ms": 2000, "total_interval_ms": 100, "max_rps": 0},
    }, pool=pool, resources={"max_parallel_downloads": max(1, model.exits),
                             "buffer_budget_bytes": max(3 * MIB, model.exits * MIB)})
    token = USE_PROXY.set(True)
    before = process_resources()
    samples = [before]
    sampling = True

    async def sample_resources() -> None:
        while sampling:
            samples.append(process_resources())
            await asyncio.sleep(.005)

    async def worker(identifier: int) -> None:
        nonlocal completed, failed, cancelled
        start = started[identifier] = time.perf_counter()
        try:
            response = await service.request(
                "GET", f"https://capacity.invalid/item/{identifier}",
                allowed_domains=("capacity.invalid",),
                max_retries=1 if model.retry_failures else 0,
                policy=ResponsePolicy(max_body_bytes=1024, max_wire_bytes=1024))
            downloaded = time.perf_counter()
            response.close()
            parse_start = time.perf_counter()
            await asyncio.sleep(.001)
            parsed = time.perf_counter()
            await asyncio.sleep(.001)
            archived = time.perf_counter()
            await asyncio.sleep(.001)
            redis_done = time.perf_counter()
            await asyncio.sleep(.002)
            sql_done = time.perf_counter()
            queue_times.append(transport_started[identifier] - start)
            download_times.append(downloaded - transport_started[identifier])
            parse_times.append(parsed - parse_start)
            archive_queue_times.append(archived - parsed)
            redis_confirm_times.append(redis_done - archived)
            sql_confirm_times.append(sql_done - redis_done)
            end_to_end.append(sql_done - start)
            completed += 1
        except asyncio.CancelledError:
            cancelled += 1
            raise
        except Exception:
            if identifier in transport_started:
                queue_times.append(transport_started[identifier] - start)
            failed += 1

    sampler = asyncio.create_task(sample_resources())
    tasks = [asyncio.create_task(worker(index)) for index in range(1, model.requests + 1)]
    if model.cancel_every:
        await asyncio.sleep(model.response_delay / 3)
        for index, task in enumerate(tasks, 1):
            if index % model.cancel_every == 0:
                task.cancel()
    start_run = time.perf_counter()
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        elapsed = time.perf_counter() - start_run
        sampling = False
        await sampler
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()
    gc.collect()
    after = process_resources()
    samples.append(after)
    rss_values = [int(item["rss_bytes"]) for item in samples if item["rss_bytes"] is not None]
    handle_values = [int(item["handles"]) for item in samples if item["handles"] is not None]
    stats = service.stats.get("virtual", {})
    cleanup = {
        "pool_waiting": pool.waiting,
        "pool_busy": sum(entry.busy for entry in pool.entries.values()),
        "pool_retired": len(pool.retired),
        "pool_close_tasks": len(pool.close_tasks),
        "http_inflight": len(service.inflight),
        "open_responses": len(service.responses),
        "buffer_used_bytes": service.buffer_budget.used,
        "global_active": service.global_active,
        "site_active": service.active.get("virtual", 0),
        "admission_waiting": int(stats.get("waiting", 0)),
    }
    return {
        "name": model.name, "devices": model.devices, "distinct_exit_ips": model.exits,
        "request_count": model.requests, "completed": completed, "failed": failed,
        "cancelled": cancelled, "attempts": attempts,
        "elapsed_seconds": round(elapsed, 4),
        "throughput_rps": round((completed + failed) / elapsed, 2) if elapsed else 0,
        "error_rate": round(failed / model.requests, 4),
        "peak_concurrency": peak,
        "latency": {"queue": latency(queue_times), "download": latency(download_times),
                    "parse": latency(parse_times), "archive_queue": latency(archive_queue_times),
                    "redis_confirm": latency(redis_confirm_times),
                    "sql_confirm": latency(sql_confirm_times),
                    "end_to_end": latency(end_to_end)},
        "directory_reads": directory.directory_reads,
        "candidate_checks": directory.candidate_checks,
        "site_cooldown_created": bool(directory.cooldowns),
        "resources": {
            "rss_before": before["rss_bytes"], "rss_peak": max(rss_values, default=None),
            "rss_after": after["rss_bytes"],
            "rss_delta": (int(after["rss_bytes"]) - int(before["rss_bytes"]))
            if after["rss_bytes"] is not None and before["rss_bytes"] is not None else None,
            "handles_before": before["handles"], "handles_peak": max(handle_values, default=None),
            "handles_after": after["handles"],
            "handles_delta": (int(after["handles"]) - int(before["handles"]))
            if after["handles"] is not None and before["handles"] is not None else None,
        },
        "cleanup": cleanup,
    }


class _ChurnClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def measure_churn(iterations: int) -> dict[str, Any]:
    """Repeatedly retire/rejoin a device and cancel a competing acquisition."""
    directory = VirtualDirectory(1, 1)
    pool = ProxyPool(directory, client_factory=lambda _url: _ChurnClient())
    before = process_resources()
    samples = [before]
    started = time.perf_counter()
    cancelled = 0
    for iteration in range(1, iterations + 1):
        entry = await pool.acquire(site="virtual")
        waiter = asyncio.create_task(pool.acquire(site="virtual"))
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        cancelled += 1
        directory.mapping.clear()
        directory.expires.clear()
        pool.refreshed_at = 0
        await pool.refresh()
        await pool.release(entry)
        directory.put(0, 1, revision=iteration)
        pool.refreshed_at = 0
        await pool.refresh()
        await pool._reap()
        if iteration % 100 == 0:
            gc.collect()
            samples.append(process_resources())
    await pool.close()
    gc.collect()
    after = process_resources()
    samples.append(after)
    rss = [int(item["rss_bytes"]) for item in samples if item["rss_bytes"] is not None]
    handles = [int(item["handles"]) for item in samples if item["handles"] is not None]
    rss_growth = rss[-1] - rss[0] if len(rss) >= 2 else None
    handle_growth = handles[-1] - handles[0] if len(handles) >= 2 else None
    cleanup = {"pool_waiting": pool.waiting, "pool_busy": 0,
               "pool_retired": len(pool.retired), "pool_close_tasks": len(pool.close_tasks)}
    stable = ((rss_growth is None or rss_growth <= 16 * MIB)
              and (handle_growth is None or handle_growth <= 8)
              and not any(cleanup.values()))
    return {
        "iterations": iterations, "cancelled_acquires": cancelled,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "directory_reads": directory.directory_reads,
        "candidate_checks": directory.candidate_checks,
        "resource_samples": samples,
        "rss_growth_bytes": rss_growth, "handle_growth": handle_growth,
        "stable_within_guardrail": stable, "cleanup": cleanup,
    }


def cleanup_is_zero(scenario: dict[str, Any]) -> bool:
    return all(value == 0 for value in scenario["cleanup"].values())


async def build_report(*, quick: bool) -> dict[str, Any]:
    matrix = (10, 30, 50, 100)
    baseline = [await measure_http(ScenarioModel(
        f"independent-{exits}", exits, exits, exits,
        response_delay=.004 if quick else .012)) for exits in matrix]
    shared = await measure_http(ScenarioModel(
        "shared-egress", 50, 10, 50, response_delay=.004 if quick else .012))
    faults = [
        await measure_http(ScenarioModel("transport-failure", 10, 10, 20,
                                         response_delay=.003, fail_every=4,
                                         retry_failures=True)),
        await measure_http(ScenarioModel("site-429", 10, 10, 10,
                                         response_delay=.003, status_every=5)),
        await measure_http(ScenarioModel("request-cancel", 10, 10, 20,
                                         response_delay=.03, cancel_every=2)),
    ]
    churn = await measure_churn(1000)
    scenarios = [*baseline, shared, *faults]
    checks = {
        "all_cleanup_zero": all(cleanup_is_zero(item) for item in scenarios)
        and not any(churn["cleanup"].values()),
        "candidate_lease_checked_per_attempt": all(
            item["candidate_checks"] >= item["attempts"] for item in scenarios),
        "shared_ip_does_not_expand_concurrency": shared["peak_concurrency"] <= 10,
        "429_created_site_cooldown": faults[1]["site_cooldown_created"],
        "cancellation_observed": faults[2]["cancelled"] > 0,
        "transport_replay_recovered": faults[0]["completed"] == faults[0]["request_count"]
        and faults[0]["attempts"] > faults[0]["request_count"],
        "churn_1000_completed": churn["iterations"] == 1000,
        "churn_resources_stable": churn["stable_within_guardrail"],
    }
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "quick-release-gate" if quick else "isolated-capacity-baseline",
        "scope": "in-process virtual directory and MockTransport; no external services",
        "model": {"exit_matrix": list(matrix), "baseline_response_delay_ms": 4 if quick else 12,
                  "parse_delay_ms": 1, "archive_queue_delay_ms": 1,
                  "redis_confirm_delay_ms": 1, "sql_confirm_delay_ms": 2,
                  "churn_cancel_iterations": 1000},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "processor": platform.processor()},
        "baseline": baseline, "shared_egress": shared, "fault_matrix": faults,
        "churn": churn, "checks": checks, "passed": all(checks.values()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="Use shorter deterministic delays for the release gate")
    parser.add_argument("--output", type=Path, default=Path("build/capacity-report.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(build_report(quick=args.quick))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if report['passed'] else 'FAIL'} isolated capacity baseline: {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
