"""Bounded waiting on existing identity and proxy discovery snapshots."""
from asyncio import sleep
from time import monotonic

from empire.features.yuanhang.node_diagnostics import snapshot


async def select_node(identity, preferred, failures, *, last_error=None, required_node=None, diagnostics=None):
    # The shared pool's maximum transport cooldown is 120 seconds. Allow its
    # five-second discovery tick, without bypassing leases or scanning Redis.
    deadline = monotonic() + 125
    initial = None
    recent = (diagnostics or {}).get('failures', [])
    last_node = recent[-1]['node'] if recent else None
    while True:
        profiles = await identity.get_profiles()
        provisioned = {code for code, profile in profiles.items() if profile.provisioned}
        nodes = provisioned & identity.online_codes()
        if required_node is not None:
            nodes &= {required_node}
        if nodes:
            return min(nodes, key=lambda code: (failures.get(code, 0), code != preferred, code))
        if initial is None:
            initial = snapshot(identity, profiles, required_node, last_node)
        if not provisioned:
            remaining = 0
        else:
            remaining = deadline - monotonic()
        if remaining <= 0:
            reason = f'；上次请求异常类型：{type(last_error).__name__}' if last_error else ''
            detail = dict(diagnostics or {})
            detail.update(preferred_node=preferred, required_node=required_node,
                          wait_started=initial, wait_finished=snapshot(identity, profiles, required_node, last_node))
            message = ('远航健康身份节点等待125秒仍不可用（离线或冷却中），保留当前断点' if provisioned
                       else '远航版没有已就绪的健康身份，保留当前断点')
            error = ValueError(message + reason + f'；最后失败节点：{last_node or "unknown"}；限定节点：{required_node or "无"}')
            error.yuanhang_diagnostics = detail
            raise error from last_error
        await sleep(min(1, remaining))
