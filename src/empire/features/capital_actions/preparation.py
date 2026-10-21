"""Read-only projection of exact SQL unit proofs; never infers source membership."""
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text

from empire.contracts.preparation import CheckEvidence
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import SCHEMA_VERSIONS, digest, ordered, validate_rows
from empire.features.capital_actions.dataset import CapitalDataset
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache

CRITERIA = ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal')


def temporal(scope, observed_at=''):
    return CheckEvidence('temporal', 'pass' if scope.purpose == 'analysis' else 'fail',
        '当前来源修订版；缺稳定事件关联及逐次修订可用日。报告期、最早预案公告日不证明实施修订当时可知；'
        '仅用于事后分析，不用于历史信号；股息率/现金收益计算尚未实现。',
        blocking=scope.purpose != 'analysis', reason='source_limit', observed_at=observed_at)


def inspect_unit(kind, unit, stored, state, scope, now):
    """Full ordered keys AND content must match before any date projection."""
    rows = ordered([decode(row) for row in stored])
    if len(rows) > 2000:
        raise ValueError('完整证券单元超过2000条安全上限')
    if any(digest(row) != original['content_hash'] for row, original in
           zip(rows, sorted(stored, key=lambda r: r['record_key']), strict=True)):
        raise ValueError('业务内容与SQL摘要不匹配')
    validate_rows(kind, unit, rows)
    proof = state.get('units', {}).get(unit, {})
    if (state.get('contract_version') != SCHEMA_VERSIONS[kind]
            or proof.get('count') != len(rows) or proof.get('digest') != digest(rows)):
        raise ValueError('完整证券单元的业务键与内容未匹配；可能包含历史保留或未知缺口，不能凭日期过滤放行')
    stamp = datetime.fromisoformat(proof.get('observed_at', ''))
    if stamp.tzinfo is None or stamp > now:
        raise ValueError('证券单元证明时间无效或超前')
    if (scope.start or scope.end) and any(row['event_date'] is None for row in rows):
        raise ValueError('单元存在未知事件日期，不能证明其在日期范围之外')
    selected = [row for row in rows if row['event_date'] is None or scope.includes(row['event_date'])]
    return selected, stamp, dict(code=unit[3:] + '.' + unit[:2],
        message=f'完整单元 {len(rows)} 条，范围内 {len(selected)} 条；'
                f'键集合 {digest(sorted(r["record_key"] for r in selected))}；内容 {digest(selected)}；'
                f'完整单元内容 {digest(rows)}；SQL来源证据 {stamp.isoformat()}')


def scoped_check(plugin, scope):
    now, findings, failed, stamps, verified, units = datetime.now(UTC), [], [], [], {}, {}
    with plugin.mysql.read_engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        conn.exec_driver_sql('START TRANSACTION READ ONLY')
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        sql = text('SELECT unified_code FROM stock WHERE LEFT(unified_code,6) IN :codes UNION '
            f'SELECT DISTINCT unified_code FROM {plugin.table} WHERE LEFT(unified_code,6) IN :codes '
            'ORDER BY unified_code LIMIT 301').bindparams(bindparam('codes', expanding=True))
        securities = list(conn.execute(sql, dict(codes=list(scope.codes))).scalars())
        if len(securities) != len(scope.codes) or {s[:6] for s in securities} != set(scope.codes):
            return tuple(CheckEvidence(k, 'fail', '证券不存在或跨市场身份不唯一，不能把缺证券当空集合') for k in CRITERIA), {}, {}
        for security in securities:
            stored = conn.execute(text(f'SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code '
                f'FROM {plugin.table} WHERE unified_code=:security ORDER BY record_key LIMIT 2001'),
                dict(security=security)).mappings().all()
            try:
                _, stamp, finding = inspect_unit(plugin.kind, security[-2:] + ':' + security[:6], stored, state, scope, now)
                findings.append(finding)
                stamps.append(stamp)
                verified[security[-2:] + ':' + security[:6]] = (
                    digest({'rows': ordered([decode(r) for r in stored]), 'manifest': None}), stamp)
                units[security] = ordered([decode(r) for r in stored])
            except (ValueError, TypeError, KeyError) as exc:
                failed.append(dict(code=security, message=str(exc)))
        conn.rollback()
    observed = min(stamps).isoformat() if stamps else ''
    message = f'{scope.label()}；已证实 {len(findings)} 个完整证券单元，未证实 {len(failed)} 个；'
    message += '证券外历史不参与此范围；完整历史原失败独立保留。日期按event_date（除息日优先，否则报告期）。'
    checks = [CheckEvidence(k, 'fail' if failed else 'pass', message,
        findings=tuple(failed + findings), observed_at=observed) for k in CRITERIA[:4]]
    fresh = not failed and bool(stamps) and min(stamps) >= now - timedelta(days=3)
    checks.append(CheckEvidence('freshness', 'pass' if fresh else 'fail',
        f'各完整证券单元SQL证据须在三日内；最早 {observed or "缺少"}；检查执行时间不替代来源时间', observed_at=observed))
    checks.append(temporal(scope, observed))
    return tuple(checks), verified, units


async def checked_units(plugin, scope):
    checks, verified, units = await plugin.mysql.read(scoped_check, plugin, scope)
    return await optional_evidence(plugin, checks, verified), units


async def preparation_check(plugin, scope):
    checks, _ = await checked_units(plugin, scope)
    return checks


async def optional_evidence(plugin, checks, verified):
    store = plugin.context.optional('redis.store') if plugin.context else None
    if store is None:
        return checks
    try:
        raw = await asyncio.wait_for(store.client.hget(f'{store.prefix}:checkpoint:{plugin.job_key}', 'cursor'), 3)
        cursor = json.loads(raw or '{}')
        if cursor.get('scope_changed') is True and cursor.get('phase') in ('fetch', 'awaiting_archive'):
            return tuple(replace(c, status='fail', blocking=True, reason='',
                measured=c.measured+'；来源范围已变化，新范围尚未确认') for c in checks)
    except Exception:
        pass
    if not verified or any(c.status != 'pass' for c in checks[:4]):
        return checks
    try:
        cache = FingerprintCache(store, plugin.archive_settings, lambda _: CapitalDataset.FINGERPRINT_VERSION)
        proofs = await asyncio.wait_for(cache.peek(plugin.kind, plugin.source, list(verified)), 3)
        now, stamps = datetime.now(UTC), []
        for unit, (checksum, sql_stamp) in verified.items():
            proof, stamp = proofs.get(unit), sql_stamp
            if proof and proof['hash'] == checksum:
                candidate = CapitalDataset.FINGERPRINT_VERSION.key(proof['version'])[0]
                if sql_stamp <= candidate <= now:
                    stamp = candidate
            stamps.append(stamp)
        observed = min(stamps).isoformat()
        fresh = min(stamps) >= now-timedelta(days=3)
        return tuple(replace(c, observed_at=observed,
            status=('pass' if fresh else 'fail') if c.criterion == 'freshness' else c.status,
            measured=(f'SQL或匹配的只读证券单元摘要；最早实际证据 {observed}；须在三日内'
                      if c.criterion == 'freshness' else c.measured)) for c in checks)
    except Exception:
        return checks
