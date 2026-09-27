"""Pure capacity calculation shared by scheduling and its read-only projection."""
from math import ceil


def capacity(group, healthy, global_limit=128):
    site_limit = min(group.max_concurrency or global_limit, global_limit)
    if group.scaling_mode == "auto":
        slots = max(1, min(healthy, site_limit))
        rate = (1000 * slots / group.proxy_interval_ms if healthy
                else 1000 / group.min_interval_ms)
        if group.max_rps:
            rate = min(rate, group.max_rps)
        interval = ceil(1000 / rate)
    else:
        slots, interval = site_limit, group.total_interval_ms
        rate = 1000 / interval
    gate = (ceil(1000 / group.max_rps) if group.max_rps else 0) if group.scaling_mode == "auto" else interval
    return {"effective_concurrency": slots, "effective_interval_ms": interval,
            "site_concurrency_limit": site_limit, "global_concurrency_limit": global_limit,
            "site_gate_interval_ms": gate,
            "healthy_egresses": healthy, "healthy_proxies": healthy,
            "rate_ceiling_rps": round(rate, 2)}
