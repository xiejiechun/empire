"""Bounded SQL content audits and disposable confirmation freshness."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text

from empire.contracts.preparation import CheckEvidence
from empire.features.yuanhang_indices import catalog_dataset, member_dataset
from empire.features.yuanhang_indices.contract import MEMBER_PROJECT, digest
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


def member_audit(conn, namespace, catalog):
    """Three queries per <=64 indices; never one SQL query per constituent."""
    state = read_state(conn, namespace, MEMBER_PROJECT, 'ths')
    units = state.get('units', {})
    codes = [r['code'] for r in catalog]
    heads, members, bad_identity = {}, {c: [] for c in codes}, False
    for first in range(0, len(codes), 64):
        params = dict(codes=codes[first:first+64])
        head_sql = text('SELECT * FROM ths_index_member_state WHERE index_code IN :codes').bindparams(bindparam('codes', expanding=True))
        heads.update((r['index_code'], r) for r in conn.execute(head_sql, params).mappings())
        member_sql = text('SELECT index_code,source_code,unified_code,name FROM ths_index_member '
            'WHERE index_code IN :codes ORDER BY index_code,source_code LIMIT 640001').bindparams(bindparam('codes', expanding=True))
        for row in conn.execute(member_sql, params).mappings():
            code = row['index_code']
            bad_identity |= row['unified_code'] != member_dataset.member_identity(row['source_code'])
            members[code].append([row['source_code'], row['name']])
            if len(members[code]) >= 10000:
                raise ValueError('成分集合超出来源单页边界')
    problems, unavailable, count, proofs = [], [], 0, {}
    for code in codes:
        rows, head, proof = members[code], heads.get(code), units.get(code, {})
        if not head:
            problems.append(code)
            continue
        available = bool(head['available'])
        checksum = digest([available, rows])
        member_dataset.normalize(type('Message', (), dict(business_key=code,
            raw_payload=dict(page=1, code=code, available=available, members=rows)))())
        if (checksum != head['member_hash'] or checksum != proof.get('hash')
                or state.get('contract_version') != 1
                or (head['member_count'] != len(rows) if available else head['member_count'] is not None)):
            problems.append(code)
        proofs[code] = (checksum, proof.get('observed_at', ''))
        if not available:
            unavailable.append(code)
        count += len(rows)
    if count > 1000000:
        raise ValueError('成分集合超出全池边界')
    return problems, unavailable, count, proofs, bad_identity


async def catalog_checks(query, scope):
    try:
        rows = await query.catalog(list(scope.index_codes) or None)
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


async def member_checks(query, scope):
    try:
        rows = await query.catalog(list(scope.index_codes) or None)
        problems, unavailable, count, proofs, bad_identity = await query.read(
            lambda conn: member_audit(conn, query.namespace, rows))
        valid = not bad_identity
        fresh = await fresh_confirmations(query, member_dataset, 'ths', proofs)
        complete = not problems and bool(rows)
        note = f'{len(rows)}项，{count}条关系；来源暂无{len(unavailable)}项，未核实{len(problems)}项'
    except (ValueError, TypeError, KeyError) as exc:
        valid, complete, fresh, unavailable, note = False, False, False, [], str(exc)
    return (evidence('fields', valid, note), evidence('keys', valid, '指数内来源编号唯一，可靠股票前缀才关联证券'),
        evidence('coverage', complete, note),
        CheckEvidence('quality', 'pass' if valid else 'fail',
            note + '；完整网页名单按原值保存；上证180/380及基金指数名单有来源口径疑点，不保证官方编制准确性',
            blocking=not valid, reason='source_limit'),
        evidence('freshness', fresh and complete, '成分最近成功核验不超过3天'),
        CheckEvidence('temporal', 'pass' if scope.purpose == 'analysis' else 'fail',
            '仅网页当前名单，不提供历史成分及权重；明确暂无保持空，不推断实际零成员',
            blocking=scope.purpose != 'analysis', reason='source_limit'))
