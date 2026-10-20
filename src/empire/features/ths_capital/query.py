"""Typed, MySQL-only browsing; each output has an independent preparation check."""
import re
from datetime import UTC, date, datetime, timedelta
from functools import partial

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.ths_capital.contract import (
    DATASET,
    JOB,
    PROJECT,
    REQUIREMENTS,
    SECTIONS,
    TABLE_SECTIONS,
    TABLES,
    digest,
    fields,
    validate,
)
from empire.features.ths_capital.dataset import CapitalPageDataset, decode, read_window
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class CapitalPageDataPlugin:
    def __init__(self, namespace='empire', archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mapping, self.mysql, self.context = CapitalPageDataset(), None, None
        self.manifest = PluginManifest('data.ths_capital', '公司资本运作查询', requires=('mysql.store',),
            provides=('ths_capital.query',), description='全部栏目结构化事实、范围游标、详情及独立完整性审计')
        self.preparation = tuple(PreparationContribution(requirement, 'ths_capital.query', '同花顺', PROJECT,
            JOB, DATASET, 'collector.ths_capital', ('tests/test_ths_capital.py', 'tests/test_ths_capital_lifecycle.py'),
            ('tests/integration/test_ths_capital_archive.py',), method='check_' + section, scoped=True,
            response_group=DATASET, analysis_quality_limits=True) for section, requirement in REQUIREMENTS.items())
        for section in SECTIONS:
            setattr(self, 'check_' + section, partial(self.preparation_check, section))

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        for table in TABLES:
            await self.mysql.require_schema(*schema_contract(table, *fields(table), 'in_window', 'content_hash', 'version_observed_at'))
        return {'ths_capital.query': self}

    async def securities(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = [dict(r) for r in conn.execute(text('SELECT unified_code,LEFT(unified_code,6) AS code,'
                    'RIGHT(unified_code,2) AS market,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings()]
                if not rows or len(rows) > 15000:
                    raise ValueError('资本运作股票池为空或超限')
                return rows
        return await self.mysql.read(read)

    async def browse(self, table='capital_funding', section='raise_', code='', start='', end='', after=None, limit=20):
        if table not in TABLES or section not in TABLE_SECTIONS[table] or not isinstance(code, str) or (
                not re.fullmatch(r'(?:\d{0,6}|\d{6}\.(SH|SZ|BJ))', code)) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('资本运作查询范围无效')
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, params = ['section=:section'], dict(section=section, limit=limit + 1)
        if code:
            clauses.append('unified_code LIKE :code')
            params['code'] = code if '.' in code else code + '%'
        for key, bound, op in (('start', scope.start, '>='), ('end', scope.end, '<=')):
            if bound:
                clauses.append('event_date' + op + ':' + key)
                params[key] = bound
        if after is not None:
            if not isinstance(after, (list, tuple)) or len(after) != 3 or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(after[1])) or not re.fullmatch('[a-f0-9]{64}', str(after[2])):
                raise ValueError('资本运作游标无效')
            if after[0] is None:
                clauses.append('event_date IS NULL AND (unified_code,record_key)<(:security,:key)')
            else:
                date.fromisoformat(after[0])
                clauses.append('((event_date,unified_code,record_key)<(:day,:security,:key) OR event_date IS NULL)')
            params.update(day=after[0], security=after[1], key=after[2])
        projection = [k for k, (_, kind) in fields(table).items() if kind != 'text']
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = conn.execute(text('SELECT ' + ','.join(projection) + ',in_window FROM ' + table +
                    ' WHERE ' + ' AND '.join(clauses) + ' ORDER BY event_date DESC,unified_code DESC,record_key DESC LIMIT :limit'), params).mappings().all()
                values = [{k: (r[k].isoformat() if isinstance(r[k], date) else str(r[k]) if fields(table).get(k, ('', ''))[1] == 'num' and r[k] is not None else r[k])
                           for k in (*projection, 'in_window')} for r in rows[:limit]]
                last = values[-1] if values else None
                return dict(rows=values, next=[last[k] for k in ('event_date', 'unified_code', 'record_key')] if len(rows) > limit else None)
        return await self.mysql.read(read)

    async def detail(self, table, key):
        if table not in TABLES or not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('资本运作详情身份无效')
        def read():
            with self.mysql.read_engine.begin() as conn:
                head = conn.execute(text('SELECT * FROM ' + table + ' WHERE record_key=:key'), dict(key=key)).mappings().first()
                if not head:
                    return None
                result = {**decode(table, head), 'in_window': bool(head['in_window'])}
                if table == 'capital_encumbrance':
                    children = conn.execute(text('SELECT * FROM capital_release WHERE parent_key=:key ORDER BY event_date,record_key LIMIT 1001'), dict(key=key)).mappings().all()
                    if len(children) > 1000:
                        raise ValueError('解除明细超过1000条')
                    result['releases'] = [{**decode('capital_release', r), 'in_window': bool(r['in_window'])} for r in children]
                return result
        return await self.mysql.read(read)

    def audit(self, scope, section=None):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, 'ths')
            keys = [r[0] for r in conn.execute(text('SELECT unified_code FROM stock ORDER BY unified_code LIMIT 15001'))]
            selected = [k for k in keys if not scope.codes or k[:6] in scope.codes]
            missing = sorted(set(scope.codes) - {k[:6] for k in selected})
            result = dict(complete=bool(selected) and not missing and len(keys) <= 15000, count=0,
                          stamps={}, hashes={}, availability={}, findings=[])
            for unit in selected:
                proof = state.get('units', {}).get(unit, {})
                try:
                    if state.get('contract_version') != 1 or proof.get('contract') != 1:
                        raise ValueError('缺少现行完整证券窗口证明')
                    rows = read_window(conn, unit)
                    selected_rows = ({t: [r for r in values if r['section'] == section] for t, values in rows.items()}
                                     if section else rows)
                    validate(unit, selected_rows, proof['availability'])
                    if (section and digest(selected_rows) != proof.get('sections', {}).get(section)) or (
                            not section and (digest(rows) != proof['digest'] or sum(map(len, rows.values())) != proof['count'])):
                        raise ValueError('当前窗口业务集合/正文与同事务证明不符')
                    stamp = self.mapping.FINGERPRINT_VERSION.key([proof['observed_at']], now=datetime.now(UTC))[0]
                    result['stamps'][unit] = stamp
                    result['hashes'][unit] = digest(dict(rows=rows, availability=proof['availability'], manifest=None))
                    result['availability'][unit] = proof['availability'].get(section) if section else proof['availability']
                    result['count'] += sum(1 for values in rows.values() for r in values if (section is None or r['section'] == section)
                                           and (r['event_date'] is None or scope.includes(r['event_date'])))
                except (ValueError, TypeError, KeyError) as exc:
                    result['complete'] = False
                    if len(result['findings']) < 100:
                        result['findings'].append(dict(security=unit, message=str(exc)))
            if missing:
                result['findings'].append(dict(message='所选证券不在股票池：' + ','.join(missing[:10])))
            return result

    async def preparation_check(self, section, request=None):
        scope = PreparationScope.parse(request)
        try:
            result = await self.mysql.read(self.audit, scope, section)
        except (ValueError, TypeError, KeyError) as exc:
            return tuple(CheckEvidence(k, 'fail', str(exc)) for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
        now, stamps = datetime.now(UTC), result['stamps']
        store = self.context.optional('redis.store') if self.context else None
        if store and stamps:
            try:
                import asyncio
                cache = FingerprintCache(store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION)
                values = await asyncio.wait_for(cache.peek(self.mapping.FINGERPRINT_NAMESPACE, 'ths', list(stamps)), 3)
                for unit, value in values.items():
                    stamp = self.mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0]
                    if value['hash'] == result['hashes'][unit] and stamp >= stamps[unit]:
                        stamps[unit] = stamp
            except Exception:
                pass  # Redis is optional evidence; never a MySQL browsing dependency.
        complete = result['complete']
        fresh = complete and bool(stamps) and all(timedelta(0) <= now - s <= timedelta(days=3) for s in stamps.values())
        measured = f"{SECTIONS[section]}，所选{len(stamps)}只证券当前窗口{result['count']}条；未列示不代表上市以来无业务"
        findings = tuple(result['findings'][:100])
        historical = scope.purpose != 'analysis'
        return tuple(CheckEvidence(k, 'pass' if complete else 'fail', measured, findings=findings)
                     for k in ('fields', 'keys', 'coverage')) + (
            CheckEvidence('quality', 'pass' if complete else 'fail', measured + '；估算、空值、原币种保留，不计算当前风险余额'),
            CheckEvidence('freshness', 'pass' if fresh else 'fail', '当前完整窗口须在3天内确认'),
            CheckEvidence('temporal', 'fail', '报告期不是公告日；当前正文含后续进展，不提供严格历史版本回放', blocking=historical),)

    async def stop(self):
        self.mysql = None

    def health(self):
        return dict(status='ok' if self.mysql else 'stopped')
