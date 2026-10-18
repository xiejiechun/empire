"""Indexed listing-event queries; SQL-only planning and optional cache evidence."""
import asyncio
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.listing_status import (
    COLUMNS,
    DATASET,
    FIRST,
    JOB,
    PROJECT,
    TYPES,
    bounds,
    months,
)
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.plugins.datasets import listing_status as mapping
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


def valid_proof(proof, month, end):
    try:
        start, expected_end = bounds(month, end)
        counts = proof['source_counts']
        mapping.FINGERPRINT_VERSION.key([proof['observed_at']])
        return (proof.get('contract') == 1 and proof['start'] == start.isoformat()
                and proof['end'] == expected_end.isoformat()
                and re.fullmatch('[0-9a-f]{64}', proof['digest']) is not None
                and isinstance(counts, list) and len(counts) == (expected_end - start).days + 1
                and all(type(n) is int and 0 <= n < 1000 for n in counts)
                and type(proof['row_count']) is int and proof['row_count'] == sum(counts)
                and 0 <= proof['row_count'] <= 5000)
    except (ValueError, TypeError, KeyError):
        return False


class ListingStatusDataPlugin:
    manifest = PluginManifest('data.listing_status', '暂停恢复终止上市查询', requires=('mysql.store',),
                              provides=('listing_status.query',), description='来源事件范围查询与完整月份证明')
    preparation = (PreparationContribution('delistings', 'listing_status.query', '通达信', PROJECT, JOB,
        DATASET, 'collector.tdx_listing_status', ('tests/test_listing_status.py',),
        ('tests/integration/test_listing_status_archive.py',), scoped=True),)

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mysql = self.context = None

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        await self.mysql.require_schema(mapping.TABLES, mapping.KEYS)
        return {'listing_status.query': self}

    async def state(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_state(conn, self.namespace, PROJECT, 'tdx')
        return await self.mysql.read(read)

    async def plan(self, through, fresh=False):
        if not isinstance(through, date) or not FIRST <= through <= datetime.now(CHINA).date():
            raise ValueError('上市状态采集上界无效')
        state = await self.state()
        proofs, expected = state.get('months', {}), months(through)
        recent = (through.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        return [m for m in expected if fresh or m >= recent or not valid_proof(proofs.get(m, {}), m, through)]

    async def list_events(self, code='', event_type='', start='', end='', after=None, limit=200, descending=False):
        if (not isinstance(code, str) or not re.fullmatch(r'(?:[0-9]{0,6}|[0-9]{6}\.(?:SH|SZ|BJ))', code)
                or event_type not in ('', *TYPES) or type(limit) is not int or not 1 <= limit <= 200 or type(descending) is not bool):
            raise ValueError('上市状态查询条件或分页上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['1=1'], dict(limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        if event_type:
            clauses.append('event_type=:type')
            params['type'] = event_type
        for key, op, value in (('start', '>=', scope.start), ('end', '<=', scope.end)):
            if value:
                clauses.append('event_date' + op + ':' + key)
                params[key] = value
        if after is not None:
            if (not isinstance(after, (list, tuple)) or len(after) != 4
                    or not all(isinstance(v, str) for v in after) or after[2] not in TYPES
                    or not re.fullmatch('[0-9a-f]{64}', after[3])):
                raise ValueError('上市状态分页游标无效')
            date.fromisoformat(after[0])
            split_unified_code(after[1])
            op = '<' if descending else '>'
            clauses.append(f'(event_date{op}:day OR (event_date=:day AND unified_code{op}:security) '
                f'OR (event_date=:day AND unified_code=:security AND event_type{op}:kind) '
                f'OR (event_date=:day AND unified_code=:security AND event_type=:kind AND record_key{op}:key))')
            params.update(day=after[0], security=after[1], kind=after[2], key=after[3])
        def read():
            with self.mysql.read_engine.connect() as conn:
                records = conn.execute(text(f'SELECT {",".join(COLUMNS[:-1])} FROM {mapping.TABLE} '
                    f'WHERE {" AND ".join(clauses)} ORDER BY ' + ','.join(k + (' DESC' if descending else '')
                    for k in ('event_date', 'unified_code', 'event_type', 'record_key')) + ' LIMIT :limit'), params).mappings().all()
            rows = [{**dict(r), 'event_date': r['event_date'].isoformat()} for r in records[:limit]]
            return dict(rows=rows, next=[rows[-1][k] for k in COLUMNS[:4]] if len(records) > limit else None)
        return await self.mysql.read(read)

    async def detail(self, key):
        if not isinstance(key, (list, tuple)) or len(key) != 4 or not all(isinstance(v, str) for v in key):
            raise ValueError('上市状态详情身份无效')
        date.fromisoformat(key[0])
        split_unified_code(key[1])
        if key[2] not in TYPES or not re.fullmatch('[0-9a-f]{64}', key[3]):
            raise ValueError('上市状态详情身份无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                row = conn.execute(text(f'SELECT description FROM {mapping.TABLE} WHERE '
                    'event_date=:event_date AND unified_code=:unified_code AND event_type=:event_type '
                    'AND record_key=:record_key'), dict(zip(COLUMNS[:4], key, strict=True))).first()
                return dict(found=row is not None, description=row[0] if row else None)
        return await self.mysql.read(read)

    async def preparation_check(self, scope=None):
        from empire.plugins.data.listing_status_checks import check
        return await check(self, PreparationScope.parse(scope))

    async def latest_observed(self, month, proof):
        stamp = proof['observed_at']
        store = self.context.optional('redis.store') if self.context else None
        if store:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: mapping.FINGERPRINT_VERSION)
                value = (await asyncio.wait_for(cache.peek(mapping.FINGERPRINT_NAMESPACE, 'tdx', [month]), 3)).get(month, {})
                if value.get('hash') == proof['digest']:
                    observed = mapping.FINGERPRINT_VERSION.key(value['version'])[0].astimezone(UTC).isoformat(timespec='microseconds')
                    stamp = max(stamp, observed)
            except Exception:
                pass
        return datetime.fromisoformat(stamp)

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
