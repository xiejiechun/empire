"""Bounded SQL catalogue/member queries and complete current-set audit."""
import asyncio
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import text

from empire.contracts.indices import (
    INDEX_LIMIT,
    JOB,
    PROJECT,
    index_code,
    member_identity,
    security_code,
)
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.datasets.indices import (
    CONTRACT_VERSION,
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    KEYS,
    TABLES,
    digest,
    normalize,
    validate_catalog,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class IndexDataPlugin:
    manifest = PluginManifest('data.indices', '当前指数查询', requires=('mysql.store',),
        provides=('indices.query',), description='同花顺目录及成分关系；来源暂无单独呈现')
    preparation = (PreparationContribution('board_history', 'indices.query', '同花顺', PROJECT, JOB,
        'index.members', 'collector.ths_indices', ('tests/test_ths_indices.py',),
        ('tests/integration/test_index_archive.py',), scoped=True),)

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.mysql, self.context = namespace, None, None
        self.archive_settings = archive_settings or {}

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(TABLES, KEYS)
        return {'indices.query': self}

    async def browse(self, mode='indices', search='', after=None, limit=200, selected_index=''):
        if (mode not in ('indices', 'members') or not isinstance(search, str) or len(search) > 100
                or type(limit) is not int or not 1 <= limit <= 500):
            raise ValueError('指数查询范围无效')
        if selected_index:
            index_code(selected_index)
        query = search.strip()
        params = dict(search='%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', limit=limit + 1)
        exact_code = mode == 'members' and bool(re.fullmatch(r'[0-9A-Z]{6}', query))
        exact_security = mode == 'members' and bool(re.fullmatch(r'[0-9]{6}\.(?:SH|SZ|BJ)', query))
        if exact_security:
            exact_code = True
            params['security'] = query
        if exact_code:
            params['code'] = query[:6]
        conditions = [] if not query or exact_code else [
            '(i.name LIKE :search OR CONVERT(i.index_code USING utf8mb4) LIKE :search OR i.source_group LIKE :search'
            + (' OR CONVERT(m.source_code USING utf8mb4) LIKE :search OR m.name LIKE :search' if mode == 'members' else '') + ')']
        if selected_index:
            conditions.append('i.index_code=:selected_index')
            params['selected_index'] = selected_index
        if exact_security:
            conditions.append('m.unified_code=:security')
        if after is not None:
            if not isinstance(after, (tuple, list)) or len(after) != (1 if mode == 'indices' else 2):
                raise ValueError('指数分页游标无效')
            params['index'] = index_code(after[0])
            if mode == 'members':
                params['member'] = security_code(after[1])
                conditions.append('(m.index_code,m.source_code)>(:index,:member)')
            else:
                conditions.append('i.index_code>:index')
        def read():
            with self.mysql.read_engine.connect() as conn:
                where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
                if mode == 'indices':
                    sql = ('SELECT i.index_code,i.name AS index_name,i.source_group,i.members_available,i.member_count '
                           'FROM stock_index i' + where + ' ORDER BY i.index_code LIMIT :limit')
                else:
                    # Complete codes use the two identity indexes; an empty search streams the member primary key.
                    members = ('(SELECT index_code,source_code FROM stock_index_member WHERE source_code=:code '
                               'UNION SELECT index_code,source_code FROM stock_index_member WHERE index_code=:code) hits '
                               'JOIN stock_index_member m ON m.index_code=hits.index_code AND m.source_code=hits.source_code'
                               if exact_code else 'stock_index_member m')
                    sql = ('SELECT m.index_code,i.name AS index_name,m.source_code,m.unified_code,m.name,i.members_available '
                           'FROM ' + members + ' STRAIGHT_JOIN stock_index i ON i.index_code=m.index_code'
                           + where + ' ORDER BY m.index_code,m.source_code LIMIT :limit')
                values = conn.execute(text(sql), params).mappings().all()
                rows = [dict(r) for r in values[:limit]]
                last = rows[-1] if rows else None
                return dict(rows=rows, next=([last['index_code']] + ([last['source_code']] if mode == 'members' else [])
                    if len(values) > limit else None))
        return await self.mysql.read(read)

    def snapshot_audit(self):
        with self.mysql.read_engine.begin() as conn:
            heads = [dict(r) for r in conn.execute(text('SELECT * FROM stock_index ORDER BY index_code LIMIT 1001')).mappings()]
            state = read_state(conn, self.namespace, PROJECT, 'ths')
            catalog = [dict(code=r['index_code'], name=r['name'], group=r['source_group']) for r in heads]
            validate_catalog(catalog)
            proofs = state.get('proofs', {})
            catalog_proof = proofs.get('catalog', {})
            complete = (state.get('contract_version') == CONTRACT_VERSION and catalog_proof.get('hash') == digest(catalog)
                        and catalog_proof.get('count') == len(catalog))
            by_code = {r['index_code']: r for r in heads}
            stamps, unavailable, unknown, count, problems = [catalog_proof.get('observed_at', '')], [], 0, 0, []
            stream = conn.execute(text('SELECT index_code,source_code,unified_code,name FROM stock_index_member '
                'ORDER BY index_code,source_code LIMIT 1000001')).mappings()
            current, members = None, []
            def finish(code, rows):
                nonlocal complete
                head = by_code[code]
                available = head['members_available']
                proof = proofs.get(code, {})
                stamps.append(proof.get('observed_at', ''))
                if available is None:
                    complete = False
                    return
                content = [bool(available), rows if available else []]
                normalize(SimpleNamespace(dataset='index.members', business_key=code,
                    raw_payload=dict(page=2, code=code, available=bool(available), members=content[1])))
                complete &= (head['member_count'] == len(rows) and head['member_hash'] == digest(content)
                             and proof.get('hash') == digest(content) and proof.get('count') == len(content[1]))
                if not available:
                    unavailable.append(code)
            visited = set()
            for row in stream:
                code = row['index_code']
                if code not in by_code or row['unified_code'] != member_identity(row['source_code']):
                    raise ValueError('指数成员目录关联或统一证券身份错误')
                if current is not None and code != current:
                    finish(current, members)
                    visited.add(current)
                    members = []
                current = code
                members.append([row['source_code'], row['name']])
                unknown += int(row['unified_code'] is None)
                count += 1
                if count > 1000000 or len(members) >= 10000:
                    raise ValueError('指数成员超过审核容量')
            if current is not None:
                finish(current, members)
                visited.add(current)
            for code in by_code.keys() - visited:
                finish(code, [])
            if len(proofs) > INDEX_LIMIT + 1:
                problems.append('状态证明超过目录边界')
                complete = False
            return heads, complete, stamps, unavailable, unknown, count, problems, proofs

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        try:
            heads, complete, stamps, unavailable, unknown, count, problems, proofs = await self.mysql.read(self.snapshot_audit)
            valid, problem = True, '；'.join(problems)
        except (ValueError, TypeError, KeyError) as exc:
            heads, complete, stamps, unavailable, unknown, count = [], False, [], [], 0, 0
            valid, problem = False, str(exc)
        now = datetime.now(UTC)
        store = self.context.optional('redis.store') if self.context else None
        cache_note = 'SQL逐指数确认'
        if complete and store:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: FINGERPRINT_VERSION)
                cached = await asyncio.wait_for(cache.peek(FINGERPRINT_NAMESPACE, 'ths', list(proofs)), 3)
                stamps = []
                for identity, proof in proofs.items():
                    value = cached.get(identity, {})
                    observed = proof['observed_at']
                    try:
                        stamp = FINGERPRINT_VERSION.key(value['version'], now=now)[0].isoformat(timespec='microseconds')
                        if value['hash'] == proof['hash'] and stamp >= observed:
                            observed = stamp
                    except (ValueError, TypeError, KeyError):
                        pass
                    stamps.append(observed)
                cache_note = 'SQL完整集合及可用Redis摘要共同确认'
            except Exception:
                cache_note = 'Redis不可用，使用SQL逐指数确认'
        try:
            dates = [FINGERPRINT_VERSION.key([s], now=now)[0] for s in stamps]
            fresh = complete and bool(dates) and all(timedelta(0) <= now - d <= timedelta(days=3) for d in dates)
        except (ValueError, TypeError, KeyError):
            fresh = False
        summary = f'{len(heads)}个指数，{count}个成员关系；来源暂无{len(unavailable)}项，未关联沪深北身份{unknown}条'
        def evidence(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        results = [evidence('fields', valid, problem or summary),
            evidence('keys', valid, problem or '指数编号唯一；同一指数成员唯一，允许跨指数重复'),
            evidence('coverage', complete, summary + ('；完整目录及各成员摘要一致' if complete else '；归档证明缺失或不一致')),
            evidence('quality', valid, problem or '成员身份、连续排序与完整来源单页已验证'),
            evidence('freshness', fresh, cache_note + '；最近成功核验不超过3天'),
            evidence('temporal', scope.purpose == 'analysis', '仅当前归属，不提供历史调样、成员生效日或权重')]
        if complete and (unavailable or unknown):
            results[-1] = CheckEvidence('temporal', 'fail', summary
                + '；来源暂无不推断零成员，旧成员仅作历史参考；仅当前归属，不提供历史调样、成员生效日或权重',
                blocking=scope.purpose != 'analysis')
        return tuple(results)

    async def stop(self):
        self.mysql = None
        self.context = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
