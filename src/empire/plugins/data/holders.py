"""MySQL-only bounded report browsing and source-window audits."""
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.holders import (
    KINDS,
    MEMBER_FIELDS,
    REPORT_FIELDS,
    project,
)
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.data.holders_audit import audit_units, cache_hashes
from empire.plugins.datasets.holders import HolderDataset, decode, read_reports
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class HolderDataPlugin:
    def __init__(self, kind, namespace='empire', archive_settings=None):
        self.kind, self.namespace, self.context, self.mysql = kind, namespace, None, None
        self.mapping, self.archive_settings = HolderDataset(), archive_settings or {}
        self.manifest = PluginManifest('data.' + kind, KINDS[kind][0] + '查询', requires=('mysql.store',),
            provides=(kind + '.query',), description='报告、当期与退出名单、窗口完整性')
        self.preparation = (PreparationContribution(kind, kind + '.query', '同花顺', project(kind),
            project(kind) + '-v1', 'holders.reports', 'collector.ths_holders',
            ('tests/test_ths_holders.py', 'tests/test_holder_combined.py', 'tests/test_holder_identity_gaps.py'),
            ('tests/integration/test_holder_archive.py', 'tests/integration/test_holder_run_outcome.py'),
            scoped=True, cache_revision=4, response_group='holders.reports', analysis_quality_limits=True),)

    async def start(self, context):
        self.context, self.mysql = context, context.get('mysql.store')
        for table, fields in (('holder_report', (*REPORT_FIELDS, 'content_hash', 'version_observed_at')),
                              ('holder_member', MEMBER_FIELDS)):
            await self.mysql.require_schema(*schema_contract(table, *fields))
        return {self.kind + '.query': self}

    async def securities(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = [dict(r) for r in conn.execute(text('SELECT unified_code,LEFT(unified_code,6) AS code,'
                    'RIGHT(unified_code,2) AS market,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings()]
                if not rows or len(rows) > 15000 or len({r['unified_code'] for r in rows}) != len(rows):
                    raise ValueError('持有人股票池为空、重复或超限')
                return rows
        return await self.mysql.read(read)

    async def browse(self, code='', start='', end='', after=None, limit=20):
        if not isinstance(code, str) or not re.fullmatch(r'(?:\d{0,6}|\d{6}\.(SH|SZ|BJ))', code) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('持有人查询范围无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['kind=:kind'], dict(kind=self.kind, limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        for key, bound, op in (('start', scope.start, '>='), ('end', scope.end, '<=')):
            if bound:
                clauses.append('report_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if not isinstance(after, (tuple, list)) or len(after) != 3 or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(after[1])) or not re.fullmatch('[a-f0-9]{64}', str(after[2])):
                raise ValueError('持有人游标无效')
            date.fromisoformat(after[0])
            clauses.append('(report_date,unified_code,report_key)<(:day,:security,:key)')
            params.update(day=after[0], security=after[1], key=after[2])
        def read():
            with self.mysql.read_engine.connect() as conn:
                heads = conn.execute(text('SELECT report_key,' + ','.join(REPORT_FIELDS) +
                    ',member_count,exit_count FROM holder_report WHERE ' + ' AND '.join(clauses) +
                    ' ORDER BY report_date DESC,unified_code DESC,report_key DESC LIMIT :limit'), params).mappings().all()
                values = [{**decode(r, REPORT_FIELDS), 'report_key': r['report_key'],
                    'member_count': r['member_count'], 'exit_count': r['exit_count']} for r in heads[:limit]]
                last = values[-1] if values else None
                return dict(rows=values, next=[last['report_date'], last['unified_code'], last['report_key']]
                            if len(heads) > limit else None)
        return await self.mysql.read(read)

    async def detail(self, key):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('持有人报告键无效')
        def read():
            with self.mysql.read_engine.begin() as conn:
                rows = read_reports(conn, [key])
                if rows and rows[0]['kind'] != self.kind:
                    raise ValueError('报告不属于本项目')
                return rows[0] if rows else None
        return await self.mysql.read(read)

    def audit(self, scope):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, project(self.kind), 'ths')
            return audit_units(conn, state, self.kind, scope, self.mapping.FINGERPRINT_VERSION)

    def cache_hashes(self, expectations):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, project(self.kind), 'ths')
            return cache_hashes(conn, state, expectations, self.kind, self.mapping.FINGERPRINT_VERSION)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        try:
            result = await self.mysql.read(self.audit, scope)
        except (ValueError, KeyError, TypeError) as exc:
            return tuple(CheckEvidence(k, 'fail', str(exc)) for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        complete = result['complete']
        now = datetime.now(UTC)
        stamps = result['stamps']
        stale = [key for key, stamp in stamps.items() if now - stamp > timedelta(days=3)]
        store = self.context.optional('redis.store') if self.context else None
        if store and stale:
            try:
                import asyncio
                cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
                cached = await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'ths', stale), 3)
                candidates = {key: value for key, value in cached.items()
                              if self.mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0] >= stamps[key]}
                hashes = await self.mysql.read(self.cache_hashes, {key: result['digests'][key] for key in candidates}) if candidates else {}
                for key, value in candidates.items():
                    if hashes.get(key) == value['hash']:
                        stamps[key] = self.mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0]
            except Exception:
                pass  # Optional Redis failure preserves the already-read SQL evidence.
        fresh = bool(stamps) and all(timedelta(0) <= now - stamp <= timedelta(days=3) for stamp in stamps.values())
        measured = (f"所选{result['securities']}只证券，{result['missing']}只缺少有效证明；本范围核验{result['reports']}份窗口报告；{result['not_published']}只股票栏目未提供；"
                    f"{result.get('notices', 0)}份变动公告非完整前十；{result.get('rank_gaps', 0)}份来源序号有缺口")
        quality_summary = '；'.join(f'{label}{count}份' for label, count in result.get('quality_counts', {}).items())
        return tuple(CheckEvidence(k, 'pass' if complete else 'fail', measured + '；报告身份、字段和来源窗口摘要', findings=result['findings'])
                     for k in ('fields', 'keys', 'coverage')) + (
            CheckEvidence('quality', 'pass' if complete and not result.get('rank_gaps') and not result.get('quality_counts') else 'fail', measured +
                          '；来源原值保留，不补造缺失持有人或数值' + ('；' + quality_summary if quality_summary else ''),
                          blocking=not (complete and (result.get('rank_gaps') or result.get('quality_counts')) and scope.purpose == 'analysis')),
            CheckEvidence('freshness', 'pass' if fresh and complete else 'fail', '所选每只证券的完整栏目确认须在3天内；缺口不冒充未提供栏目'),
            CheckEvidence('temporal', 'fail', '无公告日期；报告期不能用作信号可用日期；较早历史不在页面窗口', blocking=scope.purpose != 'analysis'),)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
