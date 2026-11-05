"""Bounded waiting on existing identity and proxy discovery snapshots."""
from asyncio import sleep
from time import monotonic


async def select_node(identity, preferred, failures, *, last_error=None, required_node=None):
    # The shared pool's maximum transport cooldown is 120 seconds. Allow its
    # five-second discovery tick, without bypassing leases or scanning Redis.
    deadline = monotonic() + 125
    while True:
        profiles = await identity.get_profiles()
        provisioned = {code for code, profile in profiles.items() if profile.provisioned}
        nodes = provisioned & identity.online_codes()
        if required_node is not None:
            nodes &= {required_node}
        if nodes:
            return min(nodes, key=lambda code: (failures.get(code, 0), code != preferred, code))
        if not provisioned:
            raise ValueError('远航版没有已就绪的健康身份，保留当前断点') from last_error
        remaining = deadline - monotonic()
        if remaining <= 0:
            reason = f'；上次请求异常类型：{type(last_error).__name__}' if last_error else ''
            raise ValueError('远航健康身份节点等待125秒仍不可用（离线或冷却中），保留当前断点'
                             + reason) from last_error
        await sleep(min(1, remaining))
