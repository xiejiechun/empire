"""Public verification of an archived current-industry snapshot."""
from datetime import UTC, datetime

from empire.features.industries.dataset import (
    CONTRACT_VERSION,
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    digest,
    validate,
)

STATE_DATASET = FINGERPRINT_NAMESPACE


def verify_current_snapshot(industries, state):
    count = validate(industries)
    if not isinstance(state, dict):
        raise ValueError('行业成分归档证明结构无效')
    if (state.get('contract_version') != CONTRACT_VERSION
            or state.get('industry_count') != len(industries)
            or state.get('member_count') != count
            or state.get('digest') != digest(industries)):
        raise ValueError('行业成分缺少一致的完整归档证明')
    FINGERPRINT_VERSION.key([state.get('observed_at')], now=datetime.now(UTC))
    return state['observed_at']
