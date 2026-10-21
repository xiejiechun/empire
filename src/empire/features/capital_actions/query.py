"""Bounded formal queries and independently measured preparation for capital actions."""
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from itertools import groupby

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source, schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import (
    CheckEvidence,
    ComputationContribution,
    PreparationContribution,
)
from empire.contracts.preparation_scope import PreparationScope
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import (
    KINDS,
    chain,
    digest,
    ordered,
    security,
    unit_key,
    validate_rows,
)
from empire.features.capital_actions.dataset import CapitalDataset
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class CapitalDataPlugin:
    output_version = 'interval-nominal-dividend-yield-v1'
    def __init__(self, kind, namespace='empire', source='tdx', archive_settings=None):
        self.kind, self.namespace, self.source = kind, namespace, source
        title, self.table, self.project_id = KINDS[kind]
        self.job_key, self.mysql = self.project_id + '-v1', None
        self.context, self.archive_settings = None, archive_settings or {}
        self.manifest = PluginManifest('data.' + kind, title + '查询', requires=('mysql.store',),
            provides=(kind + '.query', kind + '.schema'), description='规范事件查询与完整来源集合核验')
        self.preparation = (PreparationContribution(kind, kind + '.query', '通达信', self.project_id,
            self.job_key, kind + '.unit', 'collector.tdx_' + kind,
            ('tests/test_tdx_' + kind + '.py', 'tests/test_capital_lifecycle.py', 'tests/test_all_collector_prefetch.py') +
            (('tests/test_tdx_issue_details.py',) if kind == 'additional_issues' else ()),
            ('tests/integration/test_capital_archive.py', 'tests/integration/test_prefetch_pipeline.py'),
            scoped=True, cache_revision=2),)
        if kind == 'dividends':
            self.preparation += (ComputationContribution('dividend_yield', 'dividends.query',
                '通达信分红 / 巨潮日历 / 开盘啦未复权收盘价', 'empire-dividend-yield',
                ('tests/test_dividend_yield.py',), ('tests/integration/test_dividend_yield_pipeline.py',),
                self.output_version, page_id='dividends', execute_method='dividend_yield',
                method='yield_preparation_check', cache_revision=1),)

    async def start(self, context):
        self.context = context
        self.mysql = context.get('mysql.store')
        require_fixed_source(self.table, self.source)
        await self.mysql.require_schema(*schema_contract(self.table, 'name','event_date','payload','content_hash','version_observed_at'))
        if self.kind == 'dividends':
            await self.mysql.read(self._require_dividend_identity)
        if self.kind == 'additional_issues':
            await self.mysql.read(self._require_issue_contract)
        return {self.kind + '.query': self, self.kind + '.schema': self}

    def _require_issue_contract(self):
        with self.mysql.read_engine.connect() as conn:
            state = read_state(conn, self.namespace, self.project_id, self.source)
            exists = conn.execute(text('SELECT 1 FROM additional_issue WHERE TRUE LIMIT 1'),
                                  {'source': self.source}).first()
            if state.get('detail_migration_pending') or (exists and state.get('contract_version') != 3):
                raise ValueError('增发详情状态需要显式维护：关闭 Empire 后运行 scripts/migrate_issue_availability.py')

    def _require_dividend_identity(self):
        with self.mysql.read_engine.connect() as conn:
            state = read_state(conn, self.namespace, self.project_id, self.source)
            exists = conn.execute(text('SELECT 1 FROM dividend_plan WHERE TRUE LIMIT 1'),
                                  {'source': self.source}).first()
            if (state.get('identity_migration_pending') or
                    (exists and state.get('contract_version') != 3)):
                raise ValueError('分红业务键需要显式维护：关闭 Empire 后运行 scripts/migrate_dividend_identity.py')

    def _securities(self, conn):
        rows = conn.execute(text('SELECT RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code,name FROM stock WHERE TRUE '
                                 'ORDER BY market,code'), {'source': 'sina'}).mappings().all()
        if not rows or len(rows) > 15000 or len({unit_key(r) for r in rows}) != len(rows):
            raise ValueError('当前股票目录为空、重复或超出支持上限；不能建立分红股票池')
        return [security(**dict(row)) for row in rows]

    async def securities(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return self._securities(conn)
        return await self.mysql.read(read)

    async def dividend_report_dates(self):
        """One bounded projection to retain already-known non-quarter report periods."""
        def read():
            with self.mysql.read_engine.connect() as conn:
                values = conn.execute(text("SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.report_date')) "
                    "FROM dividend_plan LIMIT 501")).scalars().all()
                if len(values) > 500 or any(not isinstance(value, str) for value in values):
                    raise ValueError('已有分红报告期集合无效或超出500期')
                return values
        return await self.mysql.read(read)

    async def dividend_history_proofs(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                state = read_state(conn, self.namespace, self.project_id, self.source)
                proofs = {}
                for key, value in state.get('units', {}).items():
                    try:
                        stamp = datetime.fromisoformat(value['history_discovered_at'])
                        observed = datetime.fromisoformat(value['observed_at'])
                        if stamp.tzinfo is not None and observed.tzinfo is not None and stamp <= observed <= datetime.now(UTC):
                            proofs[key] = value['history_discovered_at']
                    except (KeyError, TypeError, ValueError):
                        continue  # Invalid proof forces source history discovery; it never skips a stock.
                return proofs
        return await self.mysql.read(read)

    async def issue_detail_candidates(self):
        """One bounded SQL read per incremental round, independent of Redis survival."""
        if self.kind != 'additional_issues':
            raise ValueError('仅增发支持详情增量比较')
        def read():
            with self.mysql.read_engine.connect() as conn:
                records = conn.execute(text('SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code FROM additional_issue WHERE TRUE '
                    'ORDER BY record_key LIMIT 10001'), {'source': self.source}).mappings().all()
                if len(records) > 10000:
                    raise ValueError('已归档增发详情比较范围超出安全上限')
                return [decode(row) for row in records]
        return await self.mysql.read(read)

    async def verified_issue_candidates(self, rows, cutoff):
        from empire.features.capital_actions.issue_candidates import verified_candidates
        return await verified_candidates(self, rows, cutoff)

    async def list_events(self, code='', market='', limit=51, offset=0, start='', end='', status='', record_key=''):
        if market not in ('', 'SH', 'SZ', 'BJ') or (code and (not code.isascii() or not code.isdigit() or len(code) > 6)):
            raise ValueError('证券查询条件无效')
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError('查询分页范围无效')
        for value in (start, end):
            if value and datetime.fromisoformat(value).date().isoformat() != value:
                raise ValueError('方案日期须为 YYYY-MM-DD')
        if start and end and start > end:
            raise ValueError('方案起止日期倒置')
        if not isinstance(status, str) or len(status) > 40 or record_key and not re.fullmatch('[0-9a-f]{64}', record_key):
            raise ValueError('方案状态或业务键无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                filters, params = [], dict(limit=limit, offset=offset)
                if code:
                    filters.append('unified_code LIKE :code')
                    params['code'] = code + ('.%' if len(code) == 6 else '%')
                if market:
                    filters.append('RIGHT(unified_code,2)=:market')
                    params['market'] = market
                for value, expression, key in ((start, 'event_date>=:start', 'start'), (end, 'event_date<=:end', 'end'),
                        (status, "JSON_UNQUOTE(JSON_EXTRACT(payload,'$.status'))=:status", 'status'),
                        (record_key, 'record_key=:record_key', 'record_key')):
                    if value:
                        filters.append(expression)
                        params[key] = value
                where = ' WHERE ' + ' AND '.join(filters) if filters else ''
                records = conn.execute(text(f'SELECT s.*,RIGHT(s.unified_code,2) AS market,'
                    f'LEFT(s.unified_code,6) AS code FROM {self.table} s JOIN ('
                    f'SELECT record_key FROM {self.table}' + where +
                    ' ORDER BY event_date DESC,RIGHT(unified_code,2),unified_code,record_key '
                    'LIMIT :limit OFFSET :offset) chosen USING(record_key) '
                    'ORDER BY s.event_date DESC,RIGHT(s.unified_code,2),s.unified_code,s.record_key'), params).mappings()
                return [decode(r) for r in records]
        return await self.mysql.read(read)

    def _audit(self):
        with self.mysql.read_engine.connect() as conn:
            state = read_state(conn, self.namespace, self.project_id, self.source)
            manifest = state.get('manifest', {})
            wanted = sorted(unit_key(r) for r in self._securities(conn)) if self.kind == 'dividends' else None
            records = conn.execution_options(stream_results=True).execute(text(
                f'SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code FROM {self.table} FORCE INDEX(ix_security_order) ORDER BY RIGHT(unified_code,2),unified_code,record_key'),
                {'source': self.source}).mappings()
            try:
                groups = ((unit, [decode(row) for row in group]) for unit, group in groupby(records, unit_key))
                def selected():
                    if wanted is None:
                        yield from groups
                        return
                    current = next(groups, None)
                    for unit in wanted:
                        while current is not None and current[0] < unit:
                            current = next(groups, None)
                        if current is not None and current[0] == unit:
                            yield current
                            current = next(groups, None)
                        else:
                            yield unit, []
                    # Drain the cursor, including out-of-pool historical securities.
                    for _ in groups:
                        pass
                count, keys, rolling, unavailable, historical_unknown = 0, [], digest([]), 0, 0
                for unit, unit_rows in selected():
                    unit_rows = ordered(unit_rows)
                    if self.kind == 'additional_issues':
                        known = [row for row in unit_rows if row['data'].get('detail') is not None]
                        historical_unknown += len(unit_rows) - len(known)
                        if not known and unit_rows:
                            continue
                        unit_rows = known
                    validate_rows(self.kind, unit, unit_rows)
                    count += len(unit_rows)
                    if self.kind == 'additional_issues':
                        unavailable += sum(row['data']['detail'].get('availability') == 'unavailable' for row in unit_rows)
                    keys.append(unit)
                    rolling = chain(rolling, unit, unit_rows)
                    if count > 1000000 or len(keys) > 15000:
                        raise ValueError('业务核验范围超过安全上限')
                actual = dict(units=len(keys), count=count, scope_hash=digest(keys), digest=rolling)
                complete = bool(manifest) and all(manifest.get(k) == v for k, v in actual.items())
                observed = datetime.fromisoformat(manifest['observed_at']) if manifest.get('observed_at') else None
                fresh = bool(observed and datetime.now(UTC) - timedelta(days=3) <= observed <= datetime.now(UTC))
                detail = f"正式查询 {count} 条 / {len(keys)} 个证券；完整来源集合{'匹配' if complete else '未证实或不匹配'}"
                if unavailable:
                    detail += f'；来源暂无可用详情 {unavailable} 条，明细字段为用途限制'
                if historical_unknown:
                    detail += (f'；另保留 {historical_unknown} 条未知历史详情，'
                               + ('完整集合摘要证实不在本次来源范围' if complete else '尚不能证明其在来源范围之外'))
                return actual, complete, fresh, detail, observed
            finally:
                records.close()

    async def preparation_check(self, request=None):
        from empire.features.capital_actions.preparation import preparation_check, temporal
        scope = PreparationScope.parse(request)
        if scope.codes:
            return await preparation_check(self, scope)
        try:
            actual, complete, fresh, detail, observed = await self.mysql.read(self._audit)
        except (KeyError, ValueError, TypeError) as exc:
            message = ('增发详情尚未补齐，请继续采集；接口失败请查看错误记录'
                       if str(exc) == '增发详情尚未补齐' else '必需字段或完整集合损坏，请重新采集核验')
            return tuple(CheckEvidence(key, 'fail', message)
                         for key in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        store = self.context.optional('redis.store') if self.context else None
        if store is not None:
            try:
                raw = await asyncio.wait_for(store.client.hget(
                    f'{store.prefix}:checkpoint:{self.job_key}', 'cursor'), 3)
                cursor = json.loads(raw or '{}')
                if cursor.get('scope_changed') is True and cursor.get('phase') in ('fetch', 'awaiting_archive'):
                    complete, fresh = False, False
                    detail += '；来源范围已变化，新范围完整证明尚未确认'
            except Exception:
                pass  # Optional negative evidence; never authorizes queue cleanup.
        if complete and store is not None:
            try:
                cache = FingerprintCache(store, self.archive_settings, lambda _: CapitalDataset.FINGERPRINT_VERSION)
                proof = (await asyncio.wait_for(cache.peek(self.kind, self.source, ['manifest']), 3)).get('manifest')
                if proof and proof['hash'] == digest({'rows': [], 'manifest': actual}):
                    stamp = CapitalDataset.FINGERPRINT_VERSION.key(proof['version'])[0]
                    if observed is not None and stamp >= observed:
                        fresh = datetime.now(UTC) - timedelta(days=3) <= stamp <= datetime.now(UTC)
                        if fresh:
                            observed = stamp
            except Exception:
                pass  # Optional read-only evidence; SQL remains independently usable.
        stamp_text = observed.isoformat() if observed else ''
        checks = [CheckEvidence(key, 'pass' if complete else 'fail', detail, observed_at=stamp_text)
                  for key in ('fields', 'keys', 'coverage', 'quality')]
        checks.append(CheckEvidence('freshness', 'pass' if fresh else 'fail',
            ('SQL / 匹配的只读可信摘要证明最近三日内核验；' if fresh else '缺少三日内可信完整范围核验；')
            + f'实际证据 {stamp_text or "缺少"}；未指定证券，保持完整来源严格核验', observed_at=stamp_text))
        checks.append(temporal(scope, stamp_text))
        return tuple(checks)

    async def distribution_summary(self, request):
        from empire.features.capital_actions.distribution import summarize_distribution
        if self.kind != 'dividends':
            raise ValueError('仅分红支持名义派息汇总')
        return await summarize_distribution(self, request)

    async def stop(self):
        self.mysql = None

    async def dividend_yield(self, request):
        from empire.features.capital_actions.dividend_yield import calculate_yield
        if self.kind != 'dividends':
            raise ValueError('仅分红支持区间名义现金股息率')
        return await calculate_yield(self, request)

    async def yield_preparation_check(self, request=None):
        from empire.features.capital_actions.dividend_yield import preparation_check
        return await preparation_check(self, request)

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
