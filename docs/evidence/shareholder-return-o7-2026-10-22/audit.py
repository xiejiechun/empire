"""Bounded read-only O7 contract audit; no collectors, source requests or writes."""
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import digest
from empire.plugins.infra.collection_state import read_state

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
SQL = Counter()


@event.listens_for(Engine, 'before_cursor_execute')
def guard(conn, cursor, statement, params, context, many):
    verb = statement.lstrip().split()[0].upper()
    if verb not in {'SELECT', 'SHOW', 'START', 'ROLLBACK'}:
        raise RuntimeError('O7 read-only audit refuses mutation: ' + verb)
    SQL[verb] += 1


def statistics(rows):
    counts = Counter()
    for row in rows:
        d = row['data']
        for field in ('issue_date', 'listing_date', 'issued_shares', 'shares_before', 'shares_after'):
            if d.get(field) is None:
                counts['missing_' + field] += 1
        if d.get('shares_before') is not None and d.get('shares_after') is not None:
            before, after, issued = (Decimal(d[f]) for f in ('shares_before', 'shares_after', 'issued_shares'))
            counts['nonpositive_capital' if min(before, after) <= 0 else 'positive_capital'] += 1
            counts['delta_equals_issued' if after - before == issued else 'delta_differs_from_issued'] += 1
        if d.get('detail') is None:
            counts['detail_unknown'] += 1
        elif d['detail'].get('availability') == 'unavailable':
            counts['detail_unavailable'] += 1
        counts['status:' + d['status']] += 1
    return dict(counts)


async def main():
    result = dict(started_at=datetime.now(UTC).isoformat(), mode='SQL READ ONLY; all Engine mutation guard',
                  source_requests=0, collectors_started=0, archivers_started=0,
                  selection_rule='600962/601966/600590 historical cross-checked candidates; '
                  '001228 fixed unknown; first 3 newest/oldest per dataset; '
                  'first key with missing capital / inconsistent delta; no success filtering')
    result['preserved_inputs_before'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / 'config.toml', ROOT / 'dist/Empire/config.toml')}
    manager = build_manager(load_config(ROOT / 'config.toml'))
    try:
        await manager.start('infra.redis')
        await manager.start('collection.records')
        store = manager.registry.get('redis.store')
        result['pending_before'] = await store.client.xlen(store.stream)
        result['datasets'] = {}
        for kind in ('additional_issues', 'rights_issues'):
            await manager.start('data.' + kind)
            q = manager.registry.get(kind + '.query')
            with q.mysql.read_engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
                conn.exec_driver_sql('START TRANSACTION READ ONLY')
                result['server_uuid'] = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
                stored = conn.execute(text(f'SELECT *,RIGHT(unified_code,2) AS market,'
                    f'LEFT(unified_code,6) AS code FROM {q.table} ORDER BY record_key LIMIT 10001')).mappings().all()
                assert len(stored) <= 10000
                rows = [decode(r) for r in stored]
                state = read_state(conn, q.namespace, q.project_id, q.source)
                selected = {r['record_key'] for r in rows if r['code'] in ('600962', '601966', '600590', '001228')}
                dated = sorted(rows, key=lambda r: (r['event_date'] or '', r['record_key']))
                selected.update(r['record_key'] for r in dated[:3] + dated[-3:])
                for condition in (
                    lambda d: d['shares_before'] is None or d['shares_after'] is None,
                    lambda d: d['shares_before'] is not None and d['shares_after'] is not None
                    and Decimal(d['shares_after']) - Decimal(d['shares_before']) != Decimal(d['issued_shares'])):
                    candidate = next((r for r in rows if condition(r['data'])), None)
                    if candidate:
                        selected.add(candidate['record_key'])
                samples = [dict(row=decode(r), content_hash=r['content_hash'],
                    hash_matches=digest(decode(r)) == r['content_hash'],
                    version_observed_at=str(r['version_observed_at']),
                    unit_proof=state.get('units', {}).get(r['market'] + ':' + r['code']))
                    for r in stored if r['record_key'] in selected]
                data = dict(count=len(rows), ordered_keys_digest=digest([r['record_key'] for r in rows]),
                    normalized_content_digest=digest(rows), stats=statistics(rows),
                    payload_fields=sorted({f for r in rows for f in r['data']}),
                    contract_version=state.get('contract_version'), manifest=state.get('manifest'), samples=samples)
                conn.rollback()
            # Formal queries independently reread; not claimed as same snapshot.
            data['formal_sample_queries'] = {}
            for code in sorted({s['row']['code'] for s in samples}):
                formal = await q.list_events(code=code, limit=500)
                original = [r for r in rows if r['code'] == code]
                assert sorted(formal, key=lambda r: r['record_key']) == original
                data['formal_sample_queries'][code] = dict(count=len(formal), content_hash=digest(original))
            data['scoped_preparation'] = {}
            for code in ('600962', '601966', '600590', '001228'):
                data['scoped_preparation'][code] = [vars(c) for c in await q.preparation_check(dict(codes=[code], purpose='analysis'))]
            cursor = await store.client.hget(f'{store.prefix}:checkpoint:{q.job_key}', 'cursor')
            data['checkpoint'] = json.loads(cursor or '{}')
            result['datasets'][kind] = data
        for key in sorted(await store.client.keys(f'{store.prefix}:*running*')):
            # Only key identity/type: no broad runtime payload or credentials.
            result.setdefault('running_keys', []).append(str(key))
        result['pending_after'] = await store.client.xlen(store.stream)
    finally:
        await manager.shutdown()
    result['sql_counts'] = dict(SQL)
    result['preserved_inputs_after'] = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                       for p in result['preserved_inputs_before']}
    assert result['preserved_inputs_after'] == result['preserved_inputs_before']
    result['finished_at'] = datetime.now(UTC).isoformat()
    with (OUT / 'input-audit.json').open('x', encoding='utf8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: dict(count=v['count'], stats=v['stats']) for k, v in result['datasets'].items()}, ensure_ascii=False))


asyncio.run(main())
