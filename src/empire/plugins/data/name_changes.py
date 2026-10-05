"""Bounded formal name-event queries and independent source-quality acceptance."""
import asyncio
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.name_changes import (
    CAPACITY,
    COLUMNS,
    KINDS,
    MARKETS,
    digest,
    identity,
    project,
    validate_rows,
)
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.datasets.name_changes import (
    CONTRACT,
    KEYS,
    TABLE,
    TABLES,
    NameDataset,
    read_rows,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class NameDataPlugin:
    def __init__(self, kind, namespace='empire', archive_settings=None):
        self.kind, self.namespace = kind, namespace
        self.archive_settings = archive_settings or {}
        self.mapping = NameDataset(kind)
        capability = 'names.' + kind + '.query'
        self.manifest = PluginManifest('data.names_' + kind, KINDS[kind][0] + '查询',
            requires=('mysql.store',), provides=(capability,), description='有界SQL浏览与来源质量检查')
        self.preparation = (PreparationContribution(KINDS[kind][1], capability, '通达信', project(kind),
            self.mapping.JOB, next(iter(self.mapping.DATASETS)), 'collector.tdx_' + kind + '_renames',
            ('tests/test_name_changes.py',), ('tests/integration/test_name_archive.py',), scoped=True),)
        self.mysql = self.context = None

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        await self.mysql.require_schema(TABLES, KEYS)
        return {self.manifest.provides[0]: self}

    async def list_events(self, code='', start='', end='', after=None, limit=200):
        if not isinstance(code, str) or not re.fullmatch('[0-9]{0,6}', code) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('更名查询代码或每页上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['name_kind=:kind'], dict(kind=self.kind, limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code + '%'
        for bound, op in ((scope.start, '>='), (scope.end, '<=')):
            if bound:
                key = 'start' if op == '>=' else 'end'
                clauses.append('event_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if (not isinstance(after, (tuple, list)) or len(after) != 3
                    or not all(isinstance(x, str) for x in after)
                    or not re.fullmatch('[0-9a-f]{64}', after[2])):
                raise ValueError('更名分页游标无效')
            from datetime import date

            from empire.contracts.security import split_unified_code
            date.fromisoformat(after[0])
            split_unified_code(after[1])
            clauses.append('(event_date,unified_code,record_key)>(:day,:security,:key)')
            params.update(day=after[0], security=after[1], key=after[2])
        def read():
            with self.mysql.read_engine.connect() as conn:
                values = conn.execute(text(f'SELECT record_key,{",".join(COLUMNS)} FROM {TABLE} '
                    f'WHERE {" AND ".join(clauses)} ORDER BY event_date,unified_code,record_key LIMIT :limit'), params).mappings().all()
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
        missing = sum(r[2] is None or r[3] is None for r in selected)
        chains = defaultdict(list)
        for row in rows:
            if not scope.codes or row[0][:6] in scope.codes:
                chains[row[0]].append(row)
        breaks = []
        for code, chain in chains.items():
            chain.sort(key=lambda r: (r[1], identity(r)))
            for a, b in zip(chain, chain[1:]):
                if (scope.includes(b[1]) and a[3] and b[2]
                        and ''.join(a[3].split()) != ''.join(b[2].split())):
                    breaks.append(code + ' ' + b[1])
        unknown_codes = sorted(set(scope.codes) - {r[0][:6] for r in rows})
        fresh = complete and len(stamps) == 3 and all(timedelta(0) <= now - s <= timedelta(days=3) for s in stamps)
        quality = missing == 0 and not breaks
        analysis = scope.purpose == 'analysis'
        def evidence(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        return (
            evidence('fields', complete and (analysis or missing == 0),
                f'范围内{len(selected)}条；证券/日期/行业字段及来源原值已核验；缺原名/新名{missing}条；空值保持未知'),
            evidence('keys', complete, '事件完整身份含名称组合；公司完全重复保留出现次数，股票同证券同日唯一'),
            evidence('coverage', complete and (analysis or not unknown_codes),
                '；'.join(notes) + ('；SQL规范集合与三市场来源证明一致' if complete else '；缺完整证明或SQL内容不一致')
                + ('；所选证券在完整来源响应中没有更名事件，普通查询为空是合法结果，不能据此还原首个名称：'
                   + '、'.join(unknown_codes) if unknown_codes else '')),
            evidence('quality', complete and (analysis or quality),
                f'来源内容一致；名称链不衔接{len(breaks)}处；' + '、'.join(breaks[:5]) + '；不填补来源缺口'),
            evidence('freshness', fresh, 'SQL及匹配缓存的完整核验时间须在3天内；最新事件日期不作为更新时效'),
            CheckEvidence('temporal', 'fail' if analysis or not (complete and quality and self.kind == 'security') else 'pass',
                f'普通查询保留来源事件；缺名{missing}条、断链{len(breaks)}处不阻断查阅。'
                '行业仅为接口返回标签，没有历史归属日期；更名日期不是公告可用日；'
                + ('公司早期旧新名称方向未确认，不保证完整历史全称回放' if self.kind == 'company'
                   else '缺名或断链区间不保证完整名称回放'), blocking=not (analysis and complete)),
        )

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
