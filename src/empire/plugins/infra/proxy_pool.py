"""Read-only RouterProxy discovery; connection credentials never leave this module."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from ipaddress import ip_address
from time import monotonic
from urllib.parse import quote, urlsplit

import httpx
from redis.exceptions import ResponseError

from empire.contracts.download_settings import MAX_PARALLEL_DOWNLOADS
from empire.contracts.plugin import PluginManifest
from empire.plugins.infra.proxy_index import ExitIndex

DIRECTORY = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
if redis.call('HLEN', KEYS[1]) > 5000 then return redis.error_reply('Directory item limit exceeded') end
local mapping = redis.call('HGETALL', KEYS[1])
local result, bytes = {}, 0
for i = 1, #mapping, 2 do
    bytes = bytes + #mapping[i] + #mapping[i+1]
    if bytes > 8388608 then return redis.error_reply('Directory byte limit exceeded') end
    local expires = tonumber(redis.call('ZSCORE', KEYS[2], mapping[i+1]) or '0')
    if expires > now then
        table.insert(result, mapping[i])
        -- Invalid oversize entries are counted without returning credentials/body.
        table.insert(result, #mapping[i+1] <= 4096 and mapping[i+1] or '')
        table.insert(result, tostring(expires - now))
    end
end
return result
"""

# Read one current mapping plus its producer lease atomically before assignment.
# Never send credentials back as command arguments or trust the cached lease alone.
CANDIDATE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local raw = redis.call('HGET', KEYS[1], ARGV[1])
if not raw then return {} end
if #raw > 4096 then return {} end
local expires = tonumber(redis.call('ZSCORE', KEYS[2], raw) or '0')
if expires <= now then return {} end
return {ARGV[1], raw, tostring(expires - now)}
"""


@dataclass
class Endpoint:
    code: str
    url: str = field(repr=False)
    version: str = field(repr=False)
    expires: float
    protocol: str = "SOCKS5"
    exit_ip: str = ""
    proxy_address: str = ""
    active_sites: set[str] = field(default_factory=set, repr=False)
    cooldown: float = 0
    failures: int = 0
    requests: int = 0
    last_used: float = 0
    ready_at: dict[str, float] = field(default_factory=dict, repr=False)
    client: httpx.AsyncClient | None = field(default=None, repr=False)

    @property
    def egress_identity(self):
        return self.exit_ip

    @property
    def busy(self):
        return len(self.active_sites)


_SCHEMES = {"http": "HTTP", "https": "HTTPS", "socks5": "SOCKS5", "socks5h": "SOCKS5"}
MAX_IDLE_ORIGINS_PER_DEVICE = 16


def _quote_url_component(value):
    """Encode literals while retaining percent escapes in a complete proxy URL."""
    result, index = [], 0
    while index < len(value):
        if (value[index] == "%" and index + 2 < len(value)
                and re.fullmatch(r"[0-9A-Fa-f]{2}", value[index + 1:index + 3])):
            result.append(value[index:index + 3])
            index += 3
        else:
            result.append(quote(value[index], safe=""))
            index += 1
    return "".join(result)


def parse_endpoint(code, raw, remaining):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
        raise ValueError("无效设备编号")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 4096:
        raise ValueError("代理目录格式无效")
    directory_raw = raw
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("代理目录必须为 JSON 对象") from None
    if (not isinstance(payload, dict) or payload.get("code") != code
            or not isinstance(payload.get("proxy"), str)):
        raise ValueError("代理目录字段无效")
    try:
        exit_ip = ip_address(payload.get("exit_ip", "")).compressed
    except ValueError:
        raise ValueError("代理出口 IP 无效") from None
    raw = payload["proxy"]
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", raw)
    # RouterProxy's JSON contract uses raw SOCKS5H credentials when no URL scheme
    # is supplied. Explicit URLs preserve existing escapes; raw credentials do not.
    scheme = match.group(1).lower() if match else "socks5h"
    if scheme not in _SCHEMES:
        raise ValueError("代理协议不受支持")
    authority = raw[match.end():] if match else raw
    # The last @ separates credentials, so literal @ remains valid in credentials.
    try:
        credentials, address = authority.rsplit("@", 1)
        user, password = credentials.split(":", 1)
        parsed = urlsplit("//" + address)
        if not user or not password or not parsed.hostname or not parsed.port:
            raise ValueError()
    except ValueError:
        raise ValueError("代理目录格式无效") from None
    if parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("代理目录地址无效")
    encode = _quote_url_component if match else lambda value: quote(value, safe="")
    url = f"{scheme}://{encode(user)}:{encode(password)}@{address}"
    hostname = parsed.hostname
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    proxy_address = f"{display_host}:{parsed.port}"
    version = hashlib.sha256(directory_raw.encode()).hexdigest()
    return Endpoint(code, url, version, monotonic() + float(remaining),
                    _SCHEMES[scheme], exit_ip, proxy_address)


class ProxyPool:
    def __init__(self, redis, *, client_factory=None, mapping_key="router:proxies:by-code",
                 directory_key="router:proxies:device"):
        self.redis = redis
        self.mapping_key, self.directory_key = mapping_key, directory_key
        self.entries: dict[str, Endpoint] = {}
        self.retired: list[Endpoint] = []
        self.lock = asyncio.Lock()
        self.close_tasks: dict[int, asyncio.Task] = {}
        self.ssl_context = None
        self.factory = client_factory or self._create_client
        self.error = ""
        self.invalid = 0
        self.waiting = 0
        self.closed = False
        self.changed = asyncio.Event()
        self.refreshed_at = 0.0
        self.directory_reads = 0
        self.candidate_checks = 0
        self.directory_limited = False
        self.index = ExitIndex()
        self.waiters = {}
        self.wait_timers = {}

    def _wake(self, site=None, *, all_waiters=False, device_code=None):
        keys = list(self.waiters) if all_waiters else [(site, device_code)]
        for key in keys:
            waiting = self.waiters.get(key, {})
            while waiting:
                future, _ = waiting.popitem(last=False)
                if not future.done():
                    future.set_result(None)
                    if not all_waiters:
                        break

    def _timer_wake(self, key):
        self.wait_timers.pop(key, None)
        self._wake(*key[:1], device_code=key[1])

    async def _wait(self, site, delay, *, device_code=None):
        loop = asyncio.get_running_loop()
        key = (site, device_code)
        future = loop.create_future()
        waiting = self.waiters.setdefault(key, OrderedDict())
        waiting[future] = None
        # One deadline per interchangeable waiter group. Successful reservation
        # passes the wake to the next general waiter; an unavailable candidate
        # rearms this timer. Bound identities have their own wake channel.
        deadline = loop.time() + delay
        timer = self.wait_timers.get(key)
        if timer is None or timer.when() > deadline:
            if timer:
                timer.cancel()
            self.wait_timers[key] = loop.call_at(deadline, self._timer_wake, key)
        try:
            await future
        finally:
            waiting.pop(future, None)
            if not waiting:
                timer = self.wait_timers.pop(key, None)
                if timer:
                    timer.cancel()
            # Cancellation after a wake must not strand the released slot.
            if future.cancelled():
                self._wake(site, device_code=device_code)

    def _create_client(self, url):
        if self.ssl_context is None:
            # One verified certifi trust store per pool, not one per device.
            self.ssl_context = httpx.create_ssl_context(verify=True, trust_env=False)
        return httpx.AsyncClient(proxy=url, verify=self.ssl_context, trust_env=False,
            timeout=httpx.Timeout(30, connect=10),
            # Real transfers are bounded by the downloader's shared global window.
            # A single connection here would silently serialize different sites.
            # Origins use distinct HTTP pools even through the same proxy. One
            # idle connection makes alternating sites tear each other down.
            # Keep a bounded set, with short idle expiry and the same global
            # transfer window; device retirement still owns every close.
            limits=httpx.Limits(max_connections=MAX_PARALLEL_DOWNLOADS,
                max_keepalive_connections=MAX_IDLE_ORIGINS_PER_DEVICE, keepalive_expiry=5),
            follow_redirects=False, headers={"User-Agent": "EmpireResearch/0.1 personal-research"})

    async def open_tunnel(self, entry, host, port, *, site):
        """Connect only while the shared router owns this site's proxy lease."""
        from empire.plugins.infra.proxy_tunnel import open_tunnel

        if site not in entry.active_sites or self.closed:
            raise RuntimeError("代理隧道必须持有当前网站许可")
        return await open_tunnel(entry.url, host, port)

    async def refresh(self, *, waiting=False):
        async with self.lock:
            if self.closed:
                return
            if waiting and monotonic() - self.refreshed_at < 5:
                return
            old = self.entries
            current = {}
            self.invalid = 0
            try:
                self.directory_reads += 1
                values = await self.redis.eval(DIRECTORY, 2,
                    self.mapping_key, self.directory_key)
                if self.closed:
                    return
                for i in range(0, len(values), 3):
                    try:
                        entry = parse_endpoint(*values[i:i + 3])
                    except (ValueError, TypeError, OverflowError):
                        self.invalid += 1
                        continue
                    previous = old.get(entry.code)
                    if previous and previous.version == entry.version:
                        previous.expires = entry.expires
                        entry = previous
                    current[entry.code] = entry
                self.error = ""
                self.directory_limited = False
            except Exception as exc:
                if isinstance(exc, ResponseError) and str(exc) in (
                        'Directory item limit exceeded', 'Directory byte limit exceeded'):
                    # A rejected snapshot says nothing about removals. Known
                    # candidates still require the atomic HGET/lease recheck.
                    current = old
                    self.directory_limited = True
                    self.error = "代理目录超出 5000 项或 8 MiB 上限；等待完整目录恢复"
                else:
                    self.directory_limited = False
                    self.error = "无法读取代理目录，代理请求等待恢复"
                # Fail closed; Redis errors can contain command arguments with credentials.
            self.entries = current
            self.refreshed_at = monotonic()
            for entry in old.values():
                if current.get(entry.code) is not entry:
                    self.retired.append(entry)
            self.index.sync(self.entries, self.retired)
            self._wake(all_waiters=True)
        await self._reap(wait=False)

    async def _reap(self, *, wait=True):
        # A caller may be cancelled at any await. Ownership stays here until the
        # close task has actually completed, including while shutdown is draining.
        ready = []
        for entry in list(self.retired):
            if entry.busy or not any(old is entry for old in self.retired):
                continue
            if entry.client is None:
                self.retired[:] = [old for old in self.retired if old is not entry]
                continue
            identity = id(entry)
            task = self.close_tasks.get(identity)
            if task is None:
                task = asyncio.create_task(entry.client.aclose())
                self.close_tasks[identity] = task
            ready.append((entry, task))
        for entry, task in ready:
            if not wait and not task.done():
                continue
            identity = id(entry)
            try:
                if wait:
                    await asyncio.shield(task)
                else:
                    task.result()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Retain the endpoint for a later close attempt; no exception may
                # expose the proxy URL or terminate the discovery monitor.
                if self.close_tasks.get(identity) is task:
                    self.close_tasks.pop(identity)
                self.error = "代理连接回收暂未完成，将重试"
                continue
            if self.close_tasks.get(identity) is task:
                self.close_tasks.pop(identity)
            self.retired[:] = [old for old in self.retired if old is not entry]

    def _retire(self, entry):
        if self.entries.get(entry.code) is entry:
            self.entries.pop(entry.code)
        if not any(old is entry for old in self.retired):
            self.retired.append(entry)
        group = self.index.exits.get(entry.exit_ip, {})
        if group.get(entry.code) is entry:
            group.pop(entry.code)
        if entry.busy:
            self.index.retiring.add(entry.code)
        self.index.changed(entry.exit_ip)

    async def _validate_candidate(self, entry):
        self.candidate_checks += 1
        try:
            values = await self.redis.eval(CANDIDATE, 2,
                self.mapping_key, self.directory_key, entry.code)
            current = parse_endpoint(*values) if values else None
        except (ValueError, TypeError, OverflowError):
            current = None
            self.invalid += 1
        except Exception:
            self.error = "无法核实代理目录，代理请求等待恢复"
            # Fail closed for all cached endpoints; fallback follows task policy.
            for candidate in list(self.entries.values()):
                self._retire(candidate)
            return False
        if self.closed or self.entries.get(entry.code) is not entry:
            return False
        if current is not None and current.version == entry.version:
            entry.expires = current.expires
            return True
        self._retire(entry)
        if current is not None:
            self.entries[current.code] = current
            self.index.exits.setdefault(current.exit_ip, {})[current.code] = current
            self.index.changed(current.exit_ip)
        return False

    def healthy_egress_count(self):
        return self.index.healthy_count()

    def healthy_count(self):
        return self.healthy_egress_count()

    def defer(self, entry, site, delay_ms):
        ready = monotonic() + delay_ms / 1000
        for candidate in self.index.exits.get(entry.exit_ip, {}).values():
            candidate.ready_at[site] = max(candidate.ready_at.get(site, 0), ready)
        self.index.site(site).update(entry.exit_ip, monotonic())
        self.index.site(site).compact(monotonic())

    async def acquire(self, *, fallback=False, site="", excluded=None, device_code=None):
        if device_code is not None and (not isinstance(device_code, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', device_code)):
            raise ValueError('固定代理设备编号无效')
        excluded = excluded or set()
        self.waiting += 1
        try:
            while not self.closed:
                await self.refresh(waiting=True)
                if self.closed:
                    break
                now = monotonic()
                ready = self.index.site(site)
                entry = None
                if len(excluded) < 1000:
                    if device_code is None:
                        entry = ready.take(excluded, now)
                    else:
                        candidate = self.entries.get(device_code)
                        if (candidate and candidate.code not in excluded
                                and candidate.expires > now and candidate.cooldown <= now
                                and candidate.ready_at.get(site, 0) <= now
                                and not self.index.busy[site].get(candidate.exit_ip)
                                and candidate.code not in self.index.retiring):
                            entry = candidate
                if entry is not None:
                    entry.active_sites.add(site)
                    self.index.reserve(entry, site)
                    entry.last_used = now
                    if device_code is None:
                        self._wake(site)
                    try:
                        # Reserve synchronously before the Redis await: concurrent
                        # acquisition cannot select this exit IP again for this site.
                        if not await self._validate_candidate(entry):
                            await self.release(entry, site=site)
                            continue
                        if entry.client is None:
                            entry.client = self.factory(entry.url)
                    except asyncio.CancelledError:
                        if site in entry.active_sites:
                            await self.release(entry, site=site)
                        raise
                    except Exception:
                        if site in entry.active_sites:
                            await self.release(entry, site=site)
                        self.failed(entry)
                        raise RuntimeError("代理客户端初始化失败，请检查代理协议支持") from None
                    return entry
                if device_code is not None:
                    candidate = self.entries.get(device_code)
                    eligible = bool(candidate and candidate.code not in excluded and
                        candidate.expires > now and candidate.cooldown <= now)
                elif excluded:
                    # Only failover consults the request's exclusion set. The
                    # normal allocation/health path never scans the directory.
                    eligible = len(excluded) < 1000 and any(e.code not in excluded and
                        e.expires > now and e.cooldown <= now for e in self.entries.values())
                else:
                    eligible = self.index.healthy_count() > 0
                if not eligible:
                    if device_code is not None:
                        self._wake(site, device_code=device_code)
                        raise httpx.ProxyError('绑定的代理设备当前不可用，不更换设备或退回直连')
                    if self.directory_limited:
                        self._wake(site)
                        raise httpx.ProxyError(self.error)
                    if fallback:
                        self._wake(site)
                        return None
                    if excluded:
                        self._wake(site)
                        raise httpx.ProxyError("本次请求的可用代理设备已全部失败，当前任务禁止本机直连")
                deadline = ready.deadline()
                if device_code is not None:
                    candidate = self.entries.get(device_code)
                    deadline = (max(candidate.cooldown, candidate.ready_at.get(site, 0))
                                if candidate and not self.index.busy[site].get(candidate.exit_ip)
                                else float('inf'))
                await self._wait(site, max(.001, min(self.refreshed_at + 5, deadline) - now),
                                 device_code=device_code)
            raise RuntimeError("代理池已停止")
        finally:
            self.waiting -= 1

    def failed(self, entry):
        entry.failures += 1
        entry.cooldown = monotonic() + min(120, 10 * 2 ** min(entry.failures - 1, 4))
        self.index.changed(entry.exit_ip)

    async def release(self, entry, *, site=""):
        if site not in entry.active_sites:
            raise RuntimeError("代理请求许可已释放")
        entry.active_sites.remove(site)
        self.index.release(entry, site)
        current = self.entries.get(entry.code)
        if current is not None and current.exit_ip != entry.exit_ip:
            self.index.changed(current.exit_ip)
        self._wake(site)
        for candidate in self.index.exits.get(entry.exit_ip, {}).values():
            self._wake(site, device_code=candidate.code)
        await self._reap(wait=False)

    async def snapshot(self):
        now = monotonic()
        return {"error": self.error, "waiting": self.waiting, "invalid": self.invalid,
                "directory_reads": self.directory_reads, "candidate_checks": self.candidate_checks,
                "online": sum(e.expires > now for e in self.entries.values()),
                "online_egresses": len({e.egress_identity for e in self.entries.values()
                                         if e.expires > now}),
                "devices": [{"code": e.code, "proxy_address": e.proxy_address,
                    "protocol": e.protocol, "exit_ip": e.exit_ip,
                    "remaining_seconds": max(0, int(e.expires - now)),
                    "cooldown_seconds": max(0, int(e.cooldown - now)),
                    "busy": e.busy, "requests": e.requests, "failures": e.failures}
                    for e in self.entries.values()]}

    async def close(self):
        self.closed = True
        self.changed.set()
        self._wake(all_waiters=True)
        for entry in list(self.entries.values()):
            self._retire(entry)
        await self._reap()
        if self.retired:
            raise RuntimeError("代理池仍有未回收的请求或连接")


class ProxyPoolPlugin:
    manifest = PluginManifest("infra.proxy_pool", "动态代理池", requires=("redis.store",),
        provides=("proxy.pool",), description="只读读取 RouterProxy 在线目录，自动处理上下线与故障隔离")

    def __init__(self):
        self.pool = None
        self.monitor = None

    async def start(self, context):
        self.pool = ProxyPool(context.get("redis.store").client)
        await self.pool.refresh()

        async def monitor():
            while True:
                await asyncio.sleep(5)
                await self.pool.refresh()

        self.monitor = context.spawn(monitor(), name="proxy-discovery", critical=True)
        return {"proxy.pool": self.pool}

    async def stop(self):
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        if self.pool:
            await self.pool.close()
        self.pool = None

    def health(self):
        return {"online": sum(e.expires > monotonic() for e in self.pool.entries.values()),
                "waiting": self.pool.waiting, "error": self.pool.error} if self.pool else {}
