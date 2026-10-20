"""Bounded formal ST-event queries and independent source-quality acceptance."""
import asyncio
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.st_events.contract import (
    CAPACITY,
    COLUMNS,
    KINDS,
    MARKETS,
    digest,
    project,
    validate_rows,
)
from empire.features.st_events.dataset import (
    CONTRACT,
    KEYS,
    TABLE,
    TABLES,
    StDataset,
    read_rows,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class StDataPlugin:
    def __init__(self, kind, namespace='empire', archive_settings=None):
        self.kind, self.namespace = kind, namespace
        self.archive_settings = archive_settings or {}
        self.mapping = StDataset(kind)
        capability = 'st.' + kind + '.query'
        self.manifest = PluginManifest('data.st_' + kind, KINDS[kind][0] + '查询',
            requires=('mysql.store',), provides=(capability,), description='有界SQL浏览与来源质量检查')
        self.preparation = (PreparationContribution(KINDS[kind][1], capability, '通达信', project(kind),
            self.mapping.JOB, next(iter(self.mapping.DATASETS)), 'collector.tdx_st_' + kind,
            ('tests/test_st_events.py',), ('tests/integration/test_st_archive.py',), scoped=True),)
        self.mysql = self.context = None

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        await self.mysql.require_schema(TABLES, KEYS)
        return {self.manifest.provides[0]: self}

    async def list_events(self, code='', start='', end='', after=None, limit=200, descending=False):
        if not isinstance(code, str) or not re.fullmatch(r'(?:[0-9]{0,6}|[0-9]{6}\.(?:SH|SZ|BJ))', code) or type(limit) is not int or not 1 <= limit <= 200 or type(descending) is not bool:
            raise ValueError('ST事件查询代码或每页上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['event_kind=:kind'], dict(kind=self.kind, limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        for bound, op in ((scope.start, '>='), (scope.end, '<=')):
            if bound:
                key = 'start' if op == '>=' else 'end'
                clauses.append('event_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if (not isinstance(after, (tuple, list)) or len(after) != 3
                    or not all(isinstance(x, str) for x in after)
                    or not re.fullmatch('[0-9a-f]{64}', after[2])):
                raise ValueError('ST事件分页游标无效')
            from datetime import date

            from empire.contracts.security import split_unified_code
            date.fromisoformat(after[0])
            split_unified_code(after[1])
            clauses.append('(event_date,unified_code,record_key)' + ('<' if descending else '>') + '(:day,:security,:key)')
            params.update(day=after[0], security=after[1], key=after[2])
        def read():
            with self.mysql.read_engine.connect() as conn:
                values = conn.execute(text(f'SELECT record_key,{",".join(COLUMNS)} FROM {TABLE} '
                    f'WHERE {" AND ".join(clauses)} ORDER BY ' +
                    ','.join(k + (' DESC' if descending else '') for k in ('event_date', 'unified_code', 'record_key'))
                    + ' LIMIT :limit'), params).mappings().all()
                rows = [{**dict(r), 'event_date': r['event_date'].isoformat()} for r in values[:limit]]
                last = rows[-1] if rows else None
                return dict(rows=rows, next=([last['event_date'], last['unified_code'], last['record_key']]
                                            if len(values) > limit else None))
        return await self.mysql.read(read)

    def snapshot(self):
        with self.mysql.read_engine.begin() as conn:
            rows, bad_keys = read_rows(conn, self.kind, include_keys=True)
            state = read_state(conn, self.namespace, project(self.kind), 'tdx')
            return rows, {**state, '_identity_errors': bad_keys}

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        rows, state = await self.mysql.read(self.snapshot)
        now, groups = datetime.now(UTC), {m: [] for m in MARKETS}
        for row in rows:
            groups.get(row[0][-2:], []).append(row)
        complete = (len(rows) < CAPACITY and sum(len(r) for r in groups.values()) == len(rows)
                    and state.get('_identity_errors', 0) == 0)
        notes, stamps = [], []
        cache = None
        store = self.context.optional('redis.store') if self.context else None
        if store:
            cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
        for market, values in groups.items():
            proof = state.get('markets', {}).get(market, {})
            stamp = proof.get('observed_at', '')
            try:
                count = validate_rows(self.kind, market, values)
                self.mapping.FINGERPRINT_VERSION.key([stamp], now=now)
                valid = (proof.get('contract') == CONTRACT and proof.get('digest') == digest(values)
                         and proof.get('row_count') == len(values) and proof.get('source_count') == count)
                complete &= valid
                if valid and cache:
                    try:
                        cached = (await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'tdx', [market]), 3)).get(market, {})
                        newer = self.mapping.FINGERPRINT_VERSION.key(cached['version'], now=now)[0]
                        if cached['hash'] == digest(values) and newer.isoformat(timespec='microseconds') >= stamp:
                            stamp = newer.isoformat(timespec='microseconds')
                    except Exception:
                        pass
                stamps.append(self.mapping.FINGERPRINT_VERSION.key([stamp], now=now)[0])
            except (ValueError, TypeError, KeyError):
                complete = False
            notes.append(f'{market} {len(values)}条')
        selected = [r for r in rows if (not scope.codes or r[0][:6] in scope.codes) and scope.includes(r[1])]
        missing = sum(r[2] is None or r[3] is None or r[7] is None for r in selected)
        fresh = complete and len(stamps) == 3 and all(timedelta(0) <= now - s <= timedelta(days=3) for s in stamps)
        def evidence(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        return (
            evidence('fields', complete, f'范围内{len(selected)}条；证券、日期及原因原值已核验，缺名或原因{missing}条保持未知'),
            evidence('keys', complete, '同一栏目证券日期唯一；重复A替代B拒绝发布'),
            evidence('coverage', complete, '；'.join(notes) + '；完整SQL集合与三市场来源证明比较；完整响应内无事件是合法空结果'),
            evidence('quality', complete, '保留实施/撤销栏目及前后简称、原因；不依据简称自动裁定状态'),
            evidence('freshness', fresh, 'SQL及匹配缓存的完整核验时间须在3天内'),
            CheckEvidence('temporal', 'fail', '来源事件日期不是公告可用时间；实施栏目含风险警示类型转换；不保证独立还原每日ST状态',
                          blocking=scope.purpose != 'analysis'),
        )

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
