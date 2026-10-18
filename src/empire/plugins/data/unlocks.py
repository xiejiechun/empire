"""Bounded official list/group queries and source-set verification."""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.unlocks import (
    CONTRACT,
    DATASET,
    JOB,
    MARKETS,
    PARENT_COLUMNS,
    PROJECT,
    day,
    digest,
    monthly_plan,
    valid_proof,
    validate_unit,
)
from empire.core.time import CHINA
from empire.plugins.datasets.unlocks import (
    TABLE_COLUMNS,
    UnlockDataset,
    decode,
    list_digest,
    read_unit,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class UnlockDataPlugin:
    manifest = PluginManifest('data.tdx_unlocks', '大小非解禁查询', requires=('mysql.store',),
        provides=('unlocks.tdx_query',), description='来源列表、共享明细及完整性审计')
    preparation = (PreparationContribution('unlock_schedule', 'unlocks.tdx_query', '通达信', PROJECT,
        JOB, DATASET, 'collector.tdx_unlocks', ('tests/test_tdx_unlocks.py',),
        ('tests/integration/test_tdx_unlocks_archive.py',), scoped=True),)

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mysql = self.context = None
        self.mapping = UnlockDataset()

    async def start(self, context):
        self.context, self.mysql = context, context.get('mysql.store')
        for table, columns in TABLE_COLUMNS.items():
            await self.mysql.require_schema(*schema_contract(table, *columns, 'content_hash', 'version_observed_at'))
        return {'unlocks.tdx_query': self}

    async def state(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_state(conn, self.namespace, PROJECT, 'tdx')
        return await self.mysql.read(read)

    async def list_records(self, code='', start='', end='', after=None, limit=200):
        if (not isinstance(code, str) or not re.fullmatch(r'(?:\d{0,6}|\d{6}\.(?:SH|SZ|BJ))', code)
                or type(limit) is not int or not 1 <= limit <= 200):
            raise ValueError('解禁查询证券或分页上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end), allow_future=True)
        clauses, params = ['TRUE'], {'limit': limit + 1}
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        for key, bound, op in (('start', scope.start, '>='), ('end', scope.end, '<=')):
            if bound:
                clauses.append('unlock_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if (not isinstance(after, (list, tuple)) or len(after) != 3
                    or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(after[1]))
                    or not re.fullmatch('[a-f0-9]{64}', str(after[2]))):
                raise ValueError('解禁查询游标无效')
            day(after[0])
            clauses.append('(unlock_date,unified_code,record_key)<(:day,:security,:key)')
            params.update(day=after[0], security=after[1], key=after[2])
        def read():
            with self.mysql.read_engine.connect() as conn:
                index = 'ix_security_date' if len(code) >= 6 else 'ix_date'
                rows = conn.execute(text('SELECT * FROM restricted_share_unlock FORCE INDEX (' + index + ') WHERE '
                    + ' AND '.join(clauses) + ' ORDER BY unlock_date DESC,unified_code DESC,record_key DESC LIMIT :limit'),
                    params).mappings().all()
                values = [decode(r, PARENT_COLUMNS) for r in rows[:limit]]
                last = values[-1] if values else None
                return dict(rows=values, next=[last['unlock_date'], last['unified_code'], last['record_key']]
                            if len(rows) > limit else None)
        return await self.mysql.read(read)

    async def details(self, group):
        if not isinstance(group, str) or not re.fullmatch('[a-f0-9]{64}', group):
            raise ValueError('解禁明细请求组无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = conn.execute(text('SELECT * FROM restricted_share_unlock_detail WHERE group_key=:group '
                    'ORDER BY record_key LIMIT 10001'), {'group': group}).mappings().all()
                if len(rows) > 10000:
                    raise ValueError('解禁明细请求组超限')
                return [decode(r, TABLE_COLUMNS['restricted_share_unlock_detail']) for r in rows]
        return await self.mysql.read(read)

    def audit(self, scope):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, 'tdx')
            manifest, proofs = state.get('manifest', {}), state.get('units', {})
            months = monthly_plan(manifest.get('start', ''), manifest.get('end', ''))
            units = [m + '|' + market for m in months for market in MARKETS]
            if len(units) > 7800 or len(proofs) > 7800:
                raise ValueError('解禁覆盖审计超限')
            selected = [u for u in units if (scope.start or '')[:7] <= u[:7] <= (scope.end or '9999-12')[:7]]
            complete, count, missing, empties, scanned = True, 0, 0, 0, 0
            for unit in selected:
                existing = read_unit(conn, unit)
                (pr, parents), (dr, children) = existing
                scanned += len(parents) + len(children)
                if scanned > 1100000:
                    raise ValueError('解禁审计正文总量超限')
                validate_unit(unit, parents, children)
                proof = proofs.get(unit, {})
                complete &= (valid_proof(proof) and proof['count'] == len(parents)
                    and proof['details'] == len(children) and proof['list_digest'] == list_digest(parents)
                    and proof['digest'] == digest([parents, children])
                    and all(r['content_hash'] == digest(row) for records, rows in existing
                            for r, row in zip(records, rows, strict=True)))
                selected_groups = {r['group_key'] for r in parents if scope.includes(r['unlock_date'])
                    and (not scope.codes or r['unified_code'][:6] in scope.codes)}
                chosen = [r for r in parents if r['group_key'] in selected_groups]
                count += len(chosen)
                missing += sum(r['shares'] is None for r in chosen)
                missing += sum(r['shares'] is None for r in children if r['group_key'] in selected_groups)
                empties += len({r['group_key'] for r in chosen if r['detail_status'] == 'source_empty'})
            chained = ''
            for unit in units:
                proof = proofs.get(unit, {})
                complete &= valid_proof(proof)
                chained = digest([chained, unit, proof.get('digest'), proof.get('count'), proof.get('details')])
            complete &= (state.get('contract_version') == CONTRACT and manifest.get('units') == len(units)
                and manifest.get('digest') == chained
                and manifest.get('count') == sum(proofs.get(u, {}).get('count', -1) for u in units)
                and manifest.get('details') == sum(proofs.get(u, {}).get('details', -1) for u in units)
                and (scope.start or '1990-01-01')[:7] >= months[0][:7]
                and (scope.end or f'{datetime.now(CHINA).year + 1}-12-31')[:7] <= months[-1][:7])
            try:
                stamp = self.mapping.FINGERPRINT_VERSION.key([manifest['observed_at']], now=datetime.now(UTC))[0]
                fresh = timedelta(0) <= datetime.now(UTC) - stamp <= timedelta(days=3)
            except (KeyError, TypeError, ValueError):
                fresh = False
            return bool(complete), fresh, count, missing, empties, manifest

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request, allow_future=True)
        try:
            complete, fresh, count, missing, empties, manifest = await self.mysql.read(self.audit, scope)
        except (ValueError, KeyError, TypeError) as exc:
            return tuple(CheckEvidence(k, 'fail', str(exc)) for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        store = self.context.optional('redis.store') if self.context else None
        if complete and store:
            try:
                import asyncio
                cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
                cached = (await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'tdx', ['manifest']), 3)).get('manifest', {})
                content = dict(parents=[], details=[], manifest={k: v for k, v in manifest.items() if k != 'observed_at'})
                stamp = self.mapping.FINGERPRINT_VERSION.key(cached['version'], now=datetime.now(UTC))[0]
                if cached['hash'] == digest(content) and stamp.isoformat(timespec='microseconds') >= manifest['observed_at']:
                    fresh = timedelta(0) <= datetime.now(UTC) - stamp <= timedelta(days=3)
            except Exception:
                pass
        return (
            CheckEvidence('fields', 'pass' if complete and not missing and not empties else 'fail',
                f'核验{count}条列表；必需字段缺失{missing}；来源空明细组{empties}'),
            CheckEvidence('keys', 'pass' if complete else 'fail', '列表事实与共享明细分别核对业务键集合及正文摘要'),
            CheckEvidence('coverage', 'pass' if complete else 'fail', '完整月份、三市场及最终范围集合证明核验'),
            CheckEvidence('quality', 'pass' if complete and not missing and not empties else 'fail',
                '股数精确换算；并列列表保留；共享明细不重复计数，未知不填零'),
            CheckEvidence('freshness', 'pass' if complete and fresh else 'fail', '匹配完整范围的SQL或可信摘要确认须在3天内'),
            CheckEvidence('temporal', 'fail', '来源没有公告可用日期；解禁日期不能证明历史信号已公开', blocking=scope.purpose != 'analysis'),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
