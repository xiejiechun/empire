"""Formal current-industry queries and read-only preparation evidence."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.industries.dataset import (
    CONTRACT_VERSION,
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    JOB,
    KEYS,
    PROJECT,
    TABLES,
    digest,
    read_snapshot,
    validate,
)
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class IndustryDataPlugin:
    manifest = PluginManifest('data.industries', '当前行业查询', requires=('mysql.store',),
        provides=('industries.query',), description='查询最新行业及成分；独立检查数据准备')
    preparation = (PreparationContribution('industries', 'industries.query', '同花顺', PROJECT, JOB,
        'industry.snapshot', 'collector.ths_industries', ('tests/test_ths_industries.py', 'tests/test_all_collector_prefetch.py'),
        ('tests/integration/test_industry_archive.py', 'tests/integration/test_prefetch_pipeline.py'), scoped=True),)

    def __init__(self, namespace='empire', source='ths', archive_settings=None):
        self.namespace, self.source = namespace, source
        self.archive_settings = archive_settings or {}
        self.context = self.mysql = None

    async def start(self, context):
        self.context, self.mysql = context, context.get('mysql.store')
        require_fixed_source('industry', self.source)
        await self.mysql.require_schema(TABLES, KEYS)
        return {'industries.query': self}

    def snapshot(self):
        with self.mysql.read_engine.begin() as conn:
            return (read_snapshot(conn, self.source),
                    read_state(conn, self.namespace, PROJECT, self.source))

    async def list_members(self, search='', offset=0, limit=200, industry=''):
        if (not isinstance(search, str) or len(search) > 100 or type(offset) is not int
                or not 0 <= offset <= 15000 or type(limit) is not int or not 1 <= limit <= 500):
            raise ValueError('行业查询范围无效')
        if industry and (not industry.isascii() or not industry.isdigit() or len(industry) != 6):
            raise ValueError('行业身份无效')
        def read():
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, PROJECT, self.source)
                pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                params = dict(source=self.source, search=pattern, offset=offset, limit=limit)
                where = ('(i.name LIKE :search OR m.name LIKE :search '
                         'OR CONVERT(m.unified_code USING utf8mb4) LIKE :search OR i.industry_code LIKE :search)')
                if industry:
                    where += ' AND i.industry_code=:industry'
                    params['industry'] = industry
                join = 'industry_member m JOIN industry i ON i.industry_code=m.industry_code'
                total = conn.execute(text(f'SELECT COUNT(*) FROM {join} WHERE {where}'), params).scalar_one()
                rows = conn.execute(text(f'SELECT i.industry_code,i.name AS industry_name,RIGHT(m.unified_code,2) AS market,LEFT(m.unified_code,6) AS code,m.name '
                    f'FROM {join} WHERE {where} ORDER BY i.industry_code,m.unified_code LIMIT :limit OFFSET :offset'), params).mappings()
                return dict(rows=[dict(r) for r in rows], total=total, offset=offset, limit=limit,
                            industry_count=state.get('industry_count', 0), publication=state.get('publication'))
        return await self.mysql.read(read)

    async def directory(self, search='', after='', limit=200):
        if not isinstance(search, str) or len(search) > 100 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('行业目录查询范围无效')
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        def read():
            with self.mysql.read_engine.connect() as conn:
                result = conn.execute(text('SELECT i.industry_code,i.name, '
                    '(SELECT COUNT(*) FROM industry_member m WHERE m.industry_code=i.industry_code) AS member_count '
                    'FROM industry i WHERE i.industry_code>:after AND '
                    '(i.name LIKE :search OR i.industry_code LIKE :search OR EXISTS '
                    '(SELECT 1 FROM industry_member m WHERE m.industry_code=i.industry_code AND '
                    '(m.name LIKE :search OR CONVERT(m.unified_code USING utf8mb4) LIKE :search))) '
                    'ORDER BY i.industry_code LIMIT :limit'), dict(after=after, search=pattern, limit=limit+1)).mappings().all()
                records = [dict(r) for r in result[:limit]]
                return dict(rows=records, next=records[-1]['industry_code'] if len(result) > limit else None)
        return await self.mysql.read(read)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        industries, state = await self.mysql.read(self.snapshot)
        return await self.audit(industries, state, scope)

    async def audit(self, industries, state, scope):
        now = datetime.now(UTC)
        try:
            count = validate(industries)
            valid, problem = True, ''
        except (ValueError, TypeError, KeyError) as exc:
            count, valid, problem = 0, False, str(exc)
        checksum = digest(industries)
        observed = state.get('observed_at', '')
        try:
            FINGERPRINT_VERSION.key([observed], now=now)
            sql_version_valid = True
        except (ValueError, TypeError, KeyError):
            sql_version_valid = False
        complete = (valid and state.get('contract_version') == CONTRACT_VERSION and state.get('digest') == checksum
                    and state.get('industry_count') == len(industries) and state.get('member_count') == count
                    and sql_version_valid)
        codes = {m[0] for i in industries for m in i.get('members', [])}
        absent = sorted(set(scope.codes) - codes)
        cache_note = 'SQL 确认'
        store = self.context.optional('redis.store') if self.context else None
        if store and complete:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: FINGERPRINT_VERSION)
                proofs = await asyncio.wait_for(cache.peek(FINGERPRINT_NAMESPACE, self.source, ['current']), 3)
                proof = proofs.get('current', {})
                stamp = FINGERPRINT_VERSION.key(proof['version'], now=now)[0]
                if proof['hash'] == checksum and stamp.isoformat(timespec='microseconds') >= observed:
                    observed, cache_note = stamp.isoformat(timespec='microseconds'), 'SQL 完整集合与有效 Redis 摘要一致'
            except Exception:
                cache_note = 'Redis 证据不可用，采用 SQL 确认'
        try:
            stamp = FINGERPRINT_VERSION.key([observed], now=now)[0]
            fresh = complete and timedelta(0) <= now - stamp <= timedelta(days=3)
        except (ValueError, TypeError, KeyError):
            fresh = False
        def evidence(key, ok, message):
            return CheckEvidence(key, 'pass' if ok else 'fail', message)
        summary = f'{len(industries)} 个行业、{count} 个成员；仅最新状态'
        return (evidence('fields', valid, problem or summary + '；行业编号/名称、证券/市场关联完整'),
            evidence('keys', valid, problem or '行业编号唯一，证券在本目录中唯一，规范集合已核对'),
            evidence('coverage', complete and not absent,
                     summary + ('；缺少所选证券：' + '、'.join(absent) if absent else '；整份来源摘要与正式查询比较')
                     + ('；集合证明一致' if complete else '；缺少完整归档证明或内容不一致')),
            evidence('quality', valid, problem or '名称非空，代码与市场有效；未把首屏当完整集合'),
            evidence('freshness', fresh, f'{cache_note}；最近完整请求代次 {observed or "未知"}；上限 3 个自然日'),
            evidence('temporal', scope.purpose == 'analysis',
                     '只供当前行业筛选及估值分组；无历史归属、变化记录或生效日期，不能还原历史行业'))

    async def stop(self):
        self.context = self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
