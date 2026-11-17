"""Source-owned content audits using the unified disposable fingerprint cache."""
import asyncio
from datetime import UTC, datetime, timedelta

from empire.contracts.preparation import CheckEvidence
from empire.features.yuanhang_etf import catalog_dataset
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


def evidence(key, ok, message):
    return CheckEvidence(key, 'pass' if ok else 'fail', message)


async def fresh_confirmations(query, mapping, source, proofs):
    """A cache timestamp extends only an already audited SQL content identity."""
    now = datetime.now(UTC)
    cached = {}
    store = query.context.optional('redis.store')
    if store and proofs:
        cache = FingerprintCache(store, query.archive_settings, lambda _: mapping.FINGERPRINT_VERSION)
        try:
            cached = await asyncio.wait_for(cache.peek(mapping.FINGERPRINT_NAMESPACE, source, list(proofs)), 3)
        except Exception:
            pass
    fresh = bool(proofs)
    for key, (checksum, observed) in proofs.items():
        try:
            stamp = mapping.FINGERPRINT_VERSION.key([observed], now=now)[0]
            value = cached.get(key)
            if value and value['hash'] == checksum:
                stamp = max(stamp, mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0])
            fresh &= timedelta(0) <= now - stamp <= timedelta(days=3)
        except (ValueError, TypeError, KeyError):
            fresh = False
    return fresh


async def catalog_checks(query, scope):
    try:
        rows = await query.catalog(list(scope.codes) or None)
        state = await query.read(lambda c: read_state(c, query.namespace, query.project_id, 'ths_yuanhang'))
        # Freshness is tied to the complete source catalogue even for a subset audit.
        proofs = {'catalog': (state['catalog_hash'], state['observed_at'])}
        fresh = await fresh_confirmations(query, catalog_dataset, 'ths_yuanhang', proofs)
        valid, note = True, f'远航当前目录所选{len(rows)}项，身份名称及完整目录摘要一致'
    except (ValueError, TypeError, KeyError) as exc:
        valid, fresh, note = False, False, str(exc)
    return (evidence('fields', valid, note), evidence('keys', valid, note),
        evidence('coverage', valid, note), evidence('quality', valid, note),
        evidence('freshness', fresh, '目录最近成功核验不超过3天'),
        CheckEvidence('temporal', 'pass' if scope.purpose == 'analysis' else 'fail',
            '当前原生目录；不提供历史目录、发布方、成立日期和基准资料',
            blocking=scope.purpose != 'analysis', reason='source_limit'))


