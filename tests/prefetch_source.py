"""HTTP test double with the real resource contract, sequential unless opted in."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from empire.contracts.download import ResponsePolicy
from empire.contracts.download_settings import DEFAULTS, PROFILE_FIELDS
from empire.plugins.infra.resources import ByteBudget


def prefetch_http(**values):
    configured = values.pop('response_policy', None)

    def policy(profile):
        result = configured(profile) if configured else None
        if isinstance(result, ResponsePolicy):
            return result
        limit = DEFAULTS[PROFILE_FIELDS[profile]]
        return ResponsePolicy(max_body_bytes=limit, max_wire_bytes=limit)

    return SimpleNamespace(response_policy=policy,
        buffer_budget=ByteBudget(DEFAULTS['buffer_budget_bytes']),
        parallelism=AsyncMock(return_value=1), **values)
