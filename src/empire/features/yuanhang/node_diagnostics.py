"""Bounded, credential-free evidence from existing in-memory node snapshots."""
from collections import Counter
from datetime import UTC, datetime
from time import monotonic


def failure(node, error, attempt):
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 4:
        seen.add(id(error))
        item = {'type': type(error).__name__}
        for key in ('errno', 'winerror'):
            value = getattr(error, key, None)
            if type(value) is int:
                item[key] = value
        # Only fixed infrastructure messages are permitted; arbitrary exception
        # strings can contain a credential-bearing proxy URL.
        known = {'SOCKS5 authentication method rejected', 'SOCKS5 authentication rejected',
                 'SOCKS5 destination connection rejected', 'Proxy CONNECT rejected'}
        if error.args and type(error.args[0]) is str and error.args[0] in known:
            item['reason'] = error.args[0]
        chain.append(';'.join(f'{key}={value}' for key, value in item.items()))
        error = error.__cause__ or error.__context__
    return {'node': node, 'attempt': attempt, 'at': datetime.now(UTC).isoformat(), 'causes': chain}


def snapshot(identity, profiles, required_node=None, last_node=None):
    now = monotonic()
    pool = getattr(identity, 'pool', None)
    if pool is None:
        return {'snapshot_available': False}
    entries = pool.entries
    counts, samples = Counter(), []
    for code in sorted(set(entries) | set(profiles)):
        entry, profile = entries.get(code), profiles.get(code)
        reason = ('identity_not_ready' if profile is None or not profile.provisioned else
                  'missing_directory' if entry is None else
                  'lease_expired' if entry.expires <= now else
                  'cooldown' if entry.cooldown > now else
                  'excluded_by_binding' if required_node is not None and code != required_node else 'eligible')
        counts[reason] += 1
        if len(samples) < 2 or code in (required_node, last_node):
            samples.append({'node': code, 'reason': reason,
                            'lease_seconds': round(entry.expires - now, 1) if entry else None,
                            'cooldown_seconds': round(max(0, entry.cooldown - now), 1) if entry else None})
    return {'at': datetime.now(UTC).isoformat(), 'counts': dict(counts), 'nodes': samples,
            'omitted_nodes': len(set(entries) | set(profiles)) - len(samples),
            'directory_error': bool(getattr(pool, 'error', '')),
            'directory_age_seconds': round(max(0, now - getattr(pool, 'refreshed_at', now)), 1),
            'invalid_entries': getattr(pool, 'invalid', 0)}
