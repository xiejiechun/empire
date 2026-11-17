"""Bounded confirmation policy and ephemeral validated recovery material."""
import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from empire.contracts.collector import NEXT_MAINTENANCE_DUE
from empire.plugins.pipeline.fingerprints import FingerprintCache


def valid_proof(value, now, contract=None):
    try:
        stamp = datetime.fromisoformat(value['observed_at'])
        return (stamp.tzinfo is not None and stamp <= now
                and (contract is None or value.get('contract') == contract)
                and type(value['count']) is int and 0 <= value['count'] <= 100000
                and isinstance(value['digest'], str) and re.fullmatch('[a-f0-9]{64}', value['digest']))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def needs_review(value, key, now, *, recent=False, days=90, force=False, contract=None):
    if force or not valid_proof(value, now, contract):
        return True
    stamp = datetime.fromisoformat(value['observed_at'])
    if recent:
        schedule = NEXT_MAINTENANCE_DUE.get()
        due = schedule(stamp.timestamp()) if schedule else None
        return now >= (datetime.fromtimestamp(due, UTC) if due is not None else stamp + timedelta(days=1))
    age = now - stamp
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % days
    return age >= timedelta(days=days) or (age >= timedelta(days=1) and now.date().toordinal() % days == bucket)


def proofs_fresh(proofs, now, recent, *, days=90):
    """Allow three days of scheduling lag, never use manifest time for units."""
    return bool(proofs) and all(valid_proof(p, now) and
        now - datetime.fromisoformat(p['observed_at']) <= timedelta(days=3 if recent(k) else days + 3)
        for k, p in proofs.items())


async def confirmed_proofs(query, proofs, mapping):
    """The cache supplements SQL time only when the saved content matches."""
    result = copy.deepcopy(proofs)
    store = query.context.optional('redis.store') if query.context else None
    if not store:
        return result
    cache = FingerprintCache(store, query.archive_settings, lambda _: mapping.FINGERPRINT_VERSION)
    now = datetime.now(UTC)
    keys = [k for k, p in result.items() if valid_proof(p, now) and p.get('fingerprint_hash')]
    try:
        for offset in range(0, len(keys), 200):
            found = await cache.peek(mapping.FINGERPRINT_NAMESPACE, 'tdx', keys[offset:offset + 200])
            for key, value in found.items():
                stamp = mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0]
                if (value['hash'] == result[key]['fingerprint_hash']
                        and datetime.fromisoformat(result[key]['observed_at']) <= stamp <= now):
                    result[key]['observed_at'] = stamp.isoformat(timespec='microseconds')
    except Exception:
        pass
    return result


class RecoveryStage:
    """Not a publication proof: bounded normalized units, lost on restart."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.scope, self.started, self.size, self.units = None, None, 0, {}

    def begin(self, scope, now, *, fresh=False):
        if (fresh or self.scope != scope or self.started is None
                or not timedelta(0) <= now - self.started <= timedelta(minutes=30)):
            self.clear()
            self.scope, self.started = copy.deepcopy(scope), now

    def get(self, key):
        return copy.deepcopy(self.units.get(key))

    def put(self, key, value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        if key in self.units:
            return
        if len(self.units) >= 10000 or self.size + len(encoded) > 8 * 1024**2:
            return  # Recovery is optional; the current validated unit still proceeds.
        self.units[key] = copy.deepcopy(value)
        self.size += len(encoded)
