"""MySQL-only statement browsing and explicit preparation limitations."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source, schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.data.financial_preparation import audit_financial
from empire.plugins.datasets.financial_archive import FinancialDataset
from empire.plugins.datasets.financial_statements import KINDS, REQUIRED, digest
from empire.plugins.pipeline.fingerprints import FingerprintCache


def decode(row):
    return json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']


class FinancialDataPlugin:
    def __init__(self, kind, namespace='empire', source='ths', archive_settings=None):
        self.kind, self.namespace, self.source = kind, namespace, source
        self.table, self.project_id = KINDS[kind][2], 'ths-' + kind
        self.mysql = None
        self.context, self.archive_settings = None, archive_settings or {}
        self.manifest = PluginManifest('data.' + kind, KINDS[kind][0] + '查询', requires=('mysql.store',),
            provides=(kind + '.query',), description='独立财报查询及来源覆盖、时点限制核验')
        self.preparation = (PreparationContribution(kind, kind + '.query', '同花顺', self.project_id,
            self.project_id + '-v1', kind + '.statement', 'collector.ths_' + kind,
            ('tests/test_ths_statements.py',), ('tests/integration/test_financial_archive.py',), scoped=True),)

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        require_fixed_source(self.table, self.source)
        await self.mysql.require_schema(*schema_contract(self.table, 'payload','content_hash','version_observed_at'))
        return {self.kind + '.query': self}

    def _securities(self, conn):
        values = [dict(r) for r in conn.execute(text(
            "SELECT RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code,name FROM stock WHERE TRUE ORDER BY market,code")).mappings()]
        keys = [s['market'] + ':' + s['code'] for s in values]
        if not values or len(values) > 15000 or len(set(keys)) != len(keys):
            raise ValueError('当前股票池为空、重复或超限')
        return values

    async def securities(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return self._securities(conn)
        return await self.mysql.read(read)

    async def list_statements(self, code='', limit=51, offset=0):
        if code and (not code.isascii() or not code.isdigit() or len(code) > 6):
            raise ValueError('证券代码无效')
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or not 0 <= offset <= 4500000:
            raise ValueError('分页范围无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                filters, params = [], dict(limit=limit, offset=offset)
                if code:
                    filters.append('unified_code LIKE :code')
                    params['code'] = code + ('.%' if len(code) == 6 else '%')
                where = ' WHERE ' + ' AND '.join(filters) if filters else ''
                return [decode(r) for r in conn.execute(text(f'SELECT s.payload FROM {self.table} s JOIN ('
                    f'SELECT unified_code,report_date FROM {self.table}' + where +
                    ' ORDER BY report_date DESC,RIGHT(unified_code,2),unified_code LIMIT :limit OFFSET :offset) chosen '
                    'USING (unified_code,report_date) ORDER BY s.report_date DESC,RIGHT(s.unified_code,2),s.unified_code'),
                    params).mappings()]
        return await self.mysql.read(read)

    async def list_statement_securities(self, code='', limit=51, offset=0):
        if code and (not code.isascii() or not code.isdigit() or len(code) > 6):
            raise ValueError('证券代码无效')
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError('证券分页范围无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                where = 'WHERE s.unified_code LIKE :code' if code else ''
                return [dict(r) for r in conn.execute(text(
                    f'SELECT DISTINCT RIGHT(s.unified_code,2) AS market,LEFT(s.unified_code,6) AS code,'
                    f'COALESCE(t.name,LEFT(s.unified_code,6)) AS name FROM {self.table} s '
                    'LEFT JOIN stock t ON t.unified_code=s.unified_code ' + where +
                    ' ORDER BY market,code LIMIT :limit OFFSET :offset'),
                    dict(code=code + ('.%' if len(code) == 6 else '%'), limit=limit, offset=offset)).mappings()]
        return await self.mysql.read(read)

    def _audit(self, request=None):
        return audit_financial(self, request)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        try:
            complete, fresh, count, actual, observed, findings = await self.mysql.read(self._audit) if request is None else await self.mysql.read(self._audit, request)
            detail = f'{count} 份报表；来源报告期集合及金额精度' + ('匹配' if complete else '未证实完整')
        except (ValueError, KeyError, TypeError):
            complete, fresh, count, observed, detail = False, False, 0, None, '财报缺失或规范字段/来源集合不完整'
            findings = dict(fields=0, quality=0, examples=[])
        store = self.context.optional('redis.store') if self.context else None
        if complete and store is not None:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: FinancialDataset.FINGERPRINT_VERSION)
                if scope.codes or scope.start or scope.end:
                    plan = findings.get('cache_plan', {})
                    proofs = await asyncio.wait_for(cache.peek('ths_' + self.kind, self.source, list(plan)), 3)
                    valid = bool(plan)
                    for unit, expected in plan.items():
                        proof = proofs.get(unit)
                        if not proof or proof['hash'] != expected['hash'] or not expected['observed']:
                            valid = False
                            break
                        stamp = FinancialDataset.FINGERPRINT_VERSION.key(proof['version'])[0]
                        valid &= (stamp >= datetime.fromisoformat(expected['observed']) and
                                  datetime.now(UTC) - timedelta(days=3) <= stamp <= datetime.now(UTC))
                    fresh |= valid
                else:
                    proof = (await asyncio.wait_for(cache.peek('ths_' + self.kind, self.source, ['manifest']), 3)).get('manifest')
                    if proof and proof['hash'] == digest({'rows': [], 'manifest': actual}):
                        stamp = FinancialDataset.FINGERPRINT_VERSION.key(proof['version'])[0]
                        if observed is not None and stamp >= observed:
                            fresh = datetime.now(UTC) - timedelta(days=3) <= stamp <= datetime.now(UTC)
            except Exception:
                pass  # Optional read-only evidence; unavailable Redis does not break SQL browsing.
        coverage_status = 'pass' if complete else 'unknown' if (
            findings.get('scope_unavailable') and findings.get('integrity_ok')) else 'fail'
        if not complete and findings.get('manifest_mismatch') and findings.get('integrity_ok') and store:
            try:
                control = json.loads(await asyncio.wait_for(store.client.get(
                    f'{store.prefix}:collection:control:v1'), 3) or '{}')
                if control.get('jobs', {}).get(self.project_id, {}).get('active'):
                    coverage_status = 'unknown'
                    detail += '；任务正在更新，整轮汇总尚未完成'
            except Exception:
                pass
        checks = [CheckEvidence('keys', 'pass' if findings.get('integrity_ok', complete) else 'fail', detail),
                  CheckEvidence('coverage', coverage_status, detail)]
        checks[1] = CheckEvidence('coverage', checks[1].status, detail + '；' + findings.get('scope', ''),
                                  findings=tuple(findings.get('coverage', [])))
        for criterion in ('fields', 'quality'):
            found = findings[criterion]
            measured = detail + f'；来源{criterion}问题 {found} 项'
            if criterion == 'fields':
                measured += '；本项必需核心金额：' + '、'.join(REQUIRED[self.kind])
            if found:
                measured += '；' + '；'.join(findings['examples'])
            checks.append(CheckEvidence(criterion, 'fail' if found else 'pass' if count else 'unknown', measured,
                findings=tuple(x for x in findings.get('details', []) if x['criterion'] == criterion)))
        checks.append(CheckEvidence('freshness', 'pass' if fresh else 'fail', '最近三日 SQL / 匹配的只读摘要完整核验'))
        checks.append(CheckEvidence('temporal', 'fail',
            '来源无公告日期，当前历史值可能含修订；财务分析可使用当前值，历史选股不可提前使用',
            blocking=scope.purpose == 'historical_signal'))
        return tuple(checks)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
