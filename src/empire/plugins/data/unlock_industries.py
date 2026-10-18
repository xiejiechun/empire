"""Official monthly industry queries and bounded completeness checks."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.unlock_industries import (
    COLUMNS,
    DATASET,
    JOB,
    NUMBERS,
    PROJECT,
    TABLE,
    digest,
    month,
    validate,
)
from empire.plugins.datasets.unlock_industries import UnlockIndustryDataset, decode, read_month
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class UnlockIndustryDataPlugin:
    manifest = PluginManifest('data.tdx_unlock_industries', '大小非解禁行业查询', requires=('mysql.store',),
        provides=('unlock_industries.tdx_query',))
    preparation = (PreparationContribution('unlock_industry', 'unlock_industries.tdx_query', '通达信', PROJECT,
        JOB, DATASET, 'collector.tdx_unlock_industries', ('tests/test_tdx_unlock_industries.py',),
        ('tests/integration/test_tdx_unlock_industries_archive.py',), scoped=True),)

    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mysql = self.context = None
        self.mapping = UnlockIndustryDataset()

    async def start(self, context):
        self.context, self.mysql = context, context.get('mysql.store')
        await self.mysql.require_schema(*schema_contract(TABLE, *COLUMNS, 'content_hash', 'version_observed_at'))
        return {'unlock_industries.tdx_query': self}

    async def list_records(self, industry='', start='', end='', after=None, limit=200):
        if not isinstance(industry, str) or len(industry) > 200 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('解禁行业查询条件错误')
        clauses, params = ['TRUE'], {'limit': limit + 1}
        if industry:
            clauses.append('industry=:industry')
            params['industry'] = industry
        for key, value, op in (('start', start, '>='), ('end', end, '<=')):
            if value:
                clauses.append('unlock_month' + op + ':' + key)
                params[key] = month(value)
        if start and end and start > end:
            raise ValueError('解禁行业查询月份顺序错误')
        if after is not None:
            if (not isinstance(after, (tuple, list)) or len(after) != 2
                    or not isinstance(after[1], str) or not 1 <= len(after[1]) <= 200):
                raise ValueError('解禁行业游标错误')
            clauses.append('(unlock_month,industry)<(:month,:name)')
            params.update(month=month(after[0]), name=after[1])
        def read():
            with self.mysql.read_engine.connect() as conn:
                records = conn.execute(text(f'SELECT {",".join(COLUMNS)} FROM {TABLE} WHERE '
                    + ' AND '.join(clauses) + ' ORDER BY unlock_month DESC,industry DESC LIMIT :limit'), params).mappings().all()
                rows = [decode(r) for r in records[:limit]]
                return dict(rows=rows, next=[rows[-1]['unlock_month'], rows[-1]['industry']] if len(records) > limit else None)
        return await self.mysql.read(read)

    def audit(self, scope):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, 'tdx')
            manifest, proofs = state.get('manifest', {}), state.get('units', {})
            units = manifest.get('months', [])
            if not 1 <= len(units) <= 120 or len(proofs) > 2600:
                raise ValueError('解禁行业没有可信可得目录')
            complete, count, missing, rolling = state.get('contract_version') == 1, 0, 0, ''
            selected = [u for u in units if (scope.start or '')[:7] <= u[:7] <= (scope.end or '9999-12')[:7]]
            for unit in units:
                records, rows = read_month(conn, unit)
                proof = proofs.get(unit, {})
                validate(unit, manifest['basis_date'], rows)
                complete &= (proof.get('contract') == 1 and proof.get('count') == len(rows)
                    and proof.get('basis_date') == manifest['basis_date'] and proof.get('digest') == digest(rows)
                    and all(r['content_hash'] == digest(row) for r, row in zip(records, rows, strict=True)))
                rolling = digest([rolling, unit, digest(rows), len(rows)])
                if unit in selected:
                    count += len(rows)
                    missing += sum(r[k] is None for r in rows for k in NUMBERS)
            complete &= manifest.get('digest') == rolling and manifest.get('count') == sum(proofs.get(u, {}).get('count', -1) for u in units)
            outside = bool(scope.start and scope.start[:7] < units[0][:7] or scope.end and scope.end[:7] > units[-1][:7])
            stamp = datetime.fromisoformat(manifest['observed_at'])
            fresh = timedelta(0) <= datetime.now(UTC) - stamp <= timedelta(days=3)
            return bool(complete), fresh, count, missing, outside, manifest

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request, allow_future=True)
        try:
            complete, fresh, count, missing, outside, manifest = await self.mysql.read(self.audit, scope)
        except (KeyError, TypeError, ValueError) as exc:
            return tuple(CheckEvidence(k, 'fail', str(exc)) for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        store = self.context.optional('redis.store') if self.context else None
        if complete and store:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
                cached = (await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'tdx', ['manifest']), 3)).get('manifest', {})
                content = dict(basis_date=manifest['basis_date'], rows=[],
                               manifest={k: manifest[k] for k in ('months', 'count', 'digest')})
                key = self.mapping.FINGERPRINT_VERSION.key(cached['version'], now=datetime.now(UTC))
                if cached['hash'] == digest(content) and self.mapping.FINGERPRINT_VERSION.compare(cached['version'], manifest['version']) >= 0:
                    fresh = timedelta(0) <= datetime.now(UTC) - key[1] <= timedelta(days=3)
            except Exception:
                pass
        return (
            CheckEvidence('fields', 'pass' if complete and not missing else 'fail', f'{count}条行业汇总；未知数值{missing}'),
            CheckEvidence('keys', 'pass' if complete else 'fail', '月/行业唯一集合、完整正文及内容摘要核验'),
            CheckEvidence('coverage', 'pass' if complete else 'fail', '当前可得目录完整覆盖；目录外历史不支持' if outside else '当前可得目录完整覆盖'),
            CheckEvidence('quality', 'pass' if complete and not missing else 'fail', '单位换算及基准日明确；未知不填零'),
            CheckEvidence('freshness', 'pass' if complete and fresh else 'fail', '完整目录SQL或可信摘要确认不超过3天'),
            CheckEvidence('temporal', 'fail', '没有公告可用日期；估值基准日不等于历史已知时间', blocking=scope.purpose != 'analysis'),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
