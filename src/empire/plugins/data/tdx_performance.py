"""One bounded query and source-set audit path for each performance entity."""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.tdx_performance import (
    SCHEMA_VERSION,
    columns,
    day,
    digest,
    identity,
    monthly_plan,
    project,
    quarterly_plan,
    validate_rows,
)
from empire.contracts.tdx_performance import (
    UNIT_KINDS as KINDS,
)
from empire.core.time import CHINA
from empire.plugins.datasets.tdx_performance import PerformanceDataset, decode, unit_where
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class PerformanceDataPlugin:
    def __init__(self, kind, namespace='empire', archive_settings=None):
        self.kind, self.namespace = kind, namespace
        title, self.table, _, _ = KINDS[kind]
        self.mapping = PerformanceDataset(kind)
        self.project_id, self.job_key = project(kind), project(kind) + '-v1'
        self.manifest = PluginManifest('data.tdx_' + kind, title + '查询', requires=('mysql.store',),
            provides=(kind + '.tdx_query',), description='结构化业务查询、完整来源集合和时间质量检查')
        self.preparation = (PreparationContribution(kind, kind + '.tdx_query', '通达信', self.project_id,
            self.job_key, kind + '.tdx_unit', 'collector.tdx_' + kind,
            (('tests/test_tdx_shareholder_changes.py',) if kind == 'shareholder_changes' else
             ('tests/test_tdx_performance.py', 'tests/test_tdx_performance_lifecycle.py')),
            (('tests/integration/test_tdx_shareholder_changes_archive.py',) if kind == 'shareholder_changes' else
             ('tests/integration/test_tdx_performance_archive.py',)), scoped=True),)
        self.mysql = self.context = None
        self.archive_settings = archive_settings or {}

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(*schema_contract(self.table, *columns(self.kind), 'content_hash', 'version_observed_at'))
        return {self.manifest.provides[0]: self}

    async def state(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_state(conn, self.namespace, self.project_id, 'tdx')
        return await self.mysql.read(read)

    async def list_records(self, code='', start='', end='', after=None, limit=200):
        if not isinstance(code, str) or not re.fullmatch(r'(?:\d{0,6}|\d{6}\.(?:SH|SZ|BJ))', code) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('查询证券或分页上限无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        field = 'statistics_date' if self.kind == 'holder_count' else 'change_end' if self.kind == 'shareholder_changes' else 'report_date'
        clauses, params = ['TRUE'], {'limit': limit + 1}
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        for key, bound, op in (('start', scope.start, '>='), ('end', scope.end, '<=')):
            if bound:
                clauses.append(field + op + ':' + key)
                params[key] = bound
        if after is not None:
            if not isinstance(after, (list, tuple)) or len(after) != 3 or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(after[1])) or not re.fullmatch('[a-f0-9]{64}', str(after[2])):
                raise ValueError('查询游标无效')
            day(after[0])
            clauses.append(f'({field},unified_code,record_key)<(:day,:security,:key)')
            params.update(day=after[0], security=after[1], key=after[2])
        def read():
            with self.mysql.read_engine.connect() as conn:
                index = (' FORCE INDEX (ix_security_date)' if len(code) >= 6 else ' FORCE INDEX (ix_date)') if self.kind == 'shareholder_changes' else ''
                records = conn.execute(text(f'SELECT * FROM {self.table}{index} WHERE {" AND ".join(clauses)} '
                    f'ORDER BY {field} DESC,unified_code DESC,record_key DESC LIMIT :limit'), params).mappings().all()
                values = [{**decode(self.kind, r), 'record_key': r['record_key']} for r in records[:limit]]
                last = values[-1] if values else None
                return dict(rows=values, next=[last[field], last['unified_code'], last['record_key']]
                            if len(records) > limit else None)
        return await self.mysql.read(read)

    def audit(self, scope):
        field = 'statistics_date' if self.kind == 'holder_count' else 'change_end' if self.kind == 'shareholder_changes' else 'report_date'
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, self.project_id, 'tdx')
            manifest, proofs = state.get('manifest', {}), state.get('units', {})
            if len(proofs) > 15000:
                raise ValueError('SQL单元证明超出支持范围')
            if self.kind == 'holder_count':
                units = sorted(proofs)
            else:
                units = [period + '|' + market for period in (monthly_plan if self.kind == 'shareholder_changes' else quarterly_plan)(manifest.get('latest', ''))
                         if self.kind != 'shareholder_changes' or period >= manifest.get('start', '9999')
                         for market in ('SH', 'SZ', 'BJ')]
            selected = [u for u in units if (not scope.codes or u[:6] in scope.codes)
                        ] if self.kind == 'holder_count' else [u for u in units if
                        ((u[:7] >= (scope.start or '')[:7] and u[:7] <= (scope.end or '9999-12')[:7])
                         if self.kind == 'shareholder_changes' else scope.includes(u[:10]))]
            selected_set = set(selected)
            actual, missing_fields, temporal_bad, count, selected_count = {}, 0, 0, 0, 0
            for key in selected:
                clause, unit_params = unit_where(self.kind, key)
                # Use the date/security index for each bounded source unit instead
                # of sorting the entire history by a computed market suffix.
                query = text(f'SELECT /*+ MAX_EXECUTION_TIME(15000) */ * FROM {self.table} '
                             f'WHERE {clause} ORDER BY record_key LIMIT 80001')
                group = conn.execution_options(stream_results=True).execute(query, unit_params).mappings()
                rows, bad = [], False
                for record in group:
                    row = decode(self.kind, record)
                    rows.append(row)
                    count += 1
                    if count > 1000000 or len(rows) > 80000:
                        raise ValueError('数据准备审计超过有界支持范围')
                    bad |= record['record_key'] != identity(self.kind, row) or record['content_hash'] != digest(row)
                    if scope.includes(row[field]) and (not scope.codes or row['unified_code'][:6] in scope.codes):
                        selected_count += 1
                        missing_fields += (row.get('holders', 0) is None or row.get('name') is None or
                            self.kind == 'shareholder_changes' and row.get('shares_changed') is None or
                            self.kind == 'earnings_forecast' and (not row.get('forecast_text') or not row.get('forecast_type')))
                        if self.kind in ('earnings_forecast', 'earnings_quick', 'earnings_report', 'shareholder_changes'):
                            temporal_bad += (not row.get('announcement_date') or
                                self.kind == 'earnings_report' and row['announcement_date'] <= row['report_date'] or
                                row['announcement_date'] > record['version_observed_at'].date().isoformat())
                if key in selected_set:
                    validate_rows(self.kind, key, rows)
                    proof = proofs.get(key, {})
                    actual[key] = not bad and proof.get('count') == len(rows) and proof.get('digest') == digest(rows) and proof.get('contract') == SCHEMA_VERSION
            for key in selected:
                if key not in actual:
                    p = proofs.get(key, {})
                    actual[key] = p.get('count') == 0 and p.get('digest') == digest([]) and p.get('contract') == SCHEMA_VERSION
            chained = ''
            for key in units:
                p = proofs.get(key, {})
                chained = digest([chained, key, p.get('digest'), p.get('count')])
            complete = (bool(units) and all(actual.values()) and state.get('contract_version') == SCHEMA_VERSION
                        and manifest.get('scope_hash') == digest(units) and manifest.get('digest') == chained
                        and manifest.get('units') == len(units)
                        and manifest.get('count') == sum(proofs.get(u, {}).get('count', -1) for u in units))
            if self.kind == 'shareholder_changes':
                required = monthly_plan(datetime.now(CHINA).date().replace(day=1).isoformat())
                complete &= (scope.start or required[0])[:7] >= manifest.get('start', '9999')[:7]
                complete &= (scope.end or required[-1])[:7] <= manifest.get('latest', '')[:7]
            now = datetime.now(UTC)
            try:
                stamp = self.mapping.FINGERPRINT_VERSION.key([manifest['observed_at']], now=now)[0]
                fresh = timedelta(0) <= now - stamp <= timedelta(days=3)
            except (KeyError, ValueError, TypeError):
                fresh = False
            return complete, fresh, selected_count, missing_fields, temporal_bad, manifest

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        try:
            complete, fresh, count, missing, temporal, manifest = await self.mysql.read(self.audit, scope)
        except (ValueError, KeyError) as exc:
            return tuple(CheckEvidence(k, 'fail', str(exc)) for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        store = self.context.optional('redis.store') if self.context else None
        if complete and store:
            try:
                import asyncio
                cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
                cached = (await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'tdx', ['manifest']), 3)).get('manifest', {})
                content = {'rows': [], 'manifest': {key: value for key, value in manifest.items() if key != 'observed_at'}}
                stamp = self.mapping.FINGERPRINT_VERSION.key(cached['version'], now=datetime.now(UTC))[0]
                if cached['hash'] == digest(content) and stamp.isoformat(timespec='microseconds') >= manifest['observed_at']:
                    fresh = timedelta(0) <= datetime.now(UTC) - stamp <= timedelta(days=3)
            except Exception:
                pass
        temporal_ok = not temporal and self.kind not in ('holder_count', 'earnings_disclosure')
        return (
            CheckEvidence('fields', 'pass' if complete and not missing else 'fail', f'核验{count}条，必需字段缺失{missing}条；源端可选空值保留'),
            CheckEvidence('keys', 'pass' if complete else 'fail', '业务身份、正文及完整单元来源集合摘要比较'),
            CheckEvidence('coverage', 'pass' if complete else 'fail', '完整单元及最终范围证明核验；历史撤回仍保留并暴露差异'),
            CheckEvidence('quality', 'pass' if complete and not missing else 'fail',
                '持股数量以股、均价元/股；来源未知数量保留NULL，开始日期保留月/日精度' if self.kind == 'shareholder_changes' else
                '金额元、比率百分数、户数整数；快报同比原口径并列保留'),
            CheckEvidence('freshness', 'pass' if fresh and complete else 'fail', 'SQL完整范围或与其内容匹配的可信缓存确认须在3天内'),
            CheckEvidence('temporal', 'pass' if temporal_ok else 'fail', f'不可确认信号可用日期{temporal}条；预约日期和股东统计日不代表公告时刻', blocking=scope.purpose != 'analysis'),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
