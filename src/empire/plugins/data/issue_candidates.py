"""Reuse a forced round's already verified details using the existing archive proof."""
from datetime import UTC, datetime

from empire.plugins.datasets.capital_actions import ordered, unit_key, validate_rows
from empire.plugins.datasets.capital_archive import CapitalDataset
from empire.plugins.pipeline.fingerprints import FingerprintCache, digest


async def verified_candidates(query, rows, cutoff):
    contract = CapitalDataset.FINGERPRINT_VERSION
    stamp = datetime.fromisoformat(cutoff)
    if stamp.tzinfo is None:
        raise ValueError('强制核实起点必须含时区')
    lower = contract.key([stamp.astimezone(UTC).isoformat(timespec='microseconds')])[0]
    store = query.context.optional('redis.store') if query.context else None
    if store is None:
        return []
    groups = {}
    for row in rows:
        groups.setdefault(unit_key(row), []).append(row)
    cache = FingerprintCache(store, query.archive_settings, lambda _: contract)
    try:
        proofs = await cache.peek('additional_issues', query.source, list(groups))
    except Exception:
        return []  # No positive archive evidence: forced details must be downloaded.
    result = []
    for unit, group in groups.items():
        group = ordered(group)
        try:
            validate_rows('additional_issues', unit, group)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
        proof = proofs.get(unit)
        try:
            eligible = proof and contract.key(proof['version'])[0] >= lower
        except (ValueError, TypeError, OverflowError):
            eligible = False
        if (eligible
                and proof['hash'] == digest({'rows': group, 'manifest': None})):
            result.extend(group)
    return result
