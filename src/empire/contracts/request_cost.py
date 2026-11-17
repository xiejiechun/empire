"""Run-local numeric costs; child download tasks share only their owner's counters."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_cost = ContextVar('request_cost', default=None)
_kind = ContextVar('request_kind', default='business')
FIELDS = ('http_attempts', 'native_attempts', 'native_queries', 'authentication_http_attempts',
          'native_auth_exchanges', 'retries', 'observed_wire_bytes', 'observed_body_bytes',
          'native_decoded_bytes')


def add_cost(field, amount=1):
    cost = _cost.get()
    if cost is not None:
        cost[field] += amount


def http_attempt():
    add_cost('http_attempts')
    if _kind.get() == 'authentication':
        add_cost('authentication_http_attempts')


@contextmanager
def request_kind(kind):
    token = _kind.set(kind)
    try:
        yield
    finally:
        _kind.reset(token)


def measured_run(method):
    @wraps(method)
    async def run(self, *args, **kwargs):
        costs = dict.fromkeys(FIELDS, 0)
        token = _cost.set(costs)
        self.stats['network_costs'] = costs
        try:
            result = await method(self, *args, **kwargs)
            return {**result, 'network_costs': dict(costs)}
        finally:
            # Kept on failure/cancel too; no payload, endpoint or identity retained.
            self.stats['network_costs'] = dict(costs)
            _cost.reset(token)
    return run
