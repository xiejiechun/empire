"""Retain pure source computation capacity until the ordered consumer closes it."""
import pickle
from dataclasses import dataclass

from empire.contracts.data import BackpressureError

MAX_SOURCE_RESULT = 16 * 1024 * 1024


def source_execute(operation, body, stock, today):
    """Explicit pure-source allowlist; never receives a response or connection."""
    from empire.features.ths_capital.source import parse

    if operation != 'ths.capital':
        raise ValueError('未知来源解析操作')
    value = parse(body, stock, today)
    size = len(pickle.dumps(value, protocol=5))
    if size > MAX_SOURCE_RESULT:
        raise BackpressureError('来源解析结果超过单元 IPC 上限；断点保留')
    return value, size


@dataclass
class ComputedSource:
    value: object
    lease: object = None

    def close(self):
        self.value = None
        if self.lease is not None:
            self.lease.release()
            self.lease = None


async def compute_source(catalog, operation, body, stock, today, *, reservation=None):
    if not catalog.compute_lane or len(body) < 8192:
        return ComputedSource(source_execute(operation, body, stock, today)[0])
    required = 2 * len(body) + 2 * MAX_SOURCE_RESULT
    budget = catalog.compute_budget
    if reservation is not None:
        if reservation.budget is not budget or not reservation.retain_bytes(required):
            raise BackpressureError('共享缓冲不足以保留来源解析输入及结果；断点保留')
        lease = None  # The ordered unit owner retains this workspace.
    else:
        lease = budget.try_reserve(required) if required <= budget.limit else None
    if lease is None and reservation is None:
        raise BackpressureError('共享缓冲不足以保留来源解析输入及结果；断点保留')
    try:
        value, size = await catalog.compute_lane.call(source_execute, operation, body, stock, today)
        if lease is not None:
            lease.shrink_to(2 * len(body) + 2 * size)
        return ComputedSource(value, lease)
    except BaseException:
        # ComputeLane settles actual work before cancellation can reach here.
        if lease is not None:
            lease.release()
        raise
