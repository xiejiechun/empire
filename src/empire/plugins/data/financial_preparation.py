"""Bounded-memory source-proof and quality audit with explicit scope."""
import json
from datetime import UTC, datetime, timedelta
from itertools import groupby

from sqlalchemy import text

from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.collectors.ths_statements import chain
from empire.plugins.datasets.financial_quality import quality_issues
from empire.plugins.datasets.financial_statements import digest, validate_rows
from empire.plugins.infra.collection_state import read_state


def audit_financial(plugin, request=None):
    scope = PreparationScope.parse(request)
    with plugin.mysql.read_engine.connect() as conn:
        # A single snapshot keeps collection_state and rows coherent during archiving.
        with conn.begin():
            state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
            stocks = plugin._securities(conn)
            keys = sorted(s['market'] + ':' + s['code'] for s in stocks
                          if not scope.codes or s['code'] in scope.codes)
            unknown_codes = set(scope.codes) - {k.split(':')[1] for k in keys}
            missing = set(keys)
            rolling, count, complete = digest([]), 0, bool(keys) and not unknown_codes
            findings = dict(fields=0, quality=0, examples=[], details=[], coverage=[],
                            scope=scope.label(), cache_plan={}, integrity_ok=complete)
            observed = []
            for market in ('BJ', 'SH', 'SZ'):
                codes = [k.split(':')[1] for k in keys if k.startswith(market + ':')]
                if not codes:
                    continue
                # Primary-key order avoids sorting hundreds of thousands of JSON bodies.
                predicates = ['RIGHT(unified_code,2)=:market']
                params = dict(source=plugin.source, market=market)
                if scope.codes:
                    names = []
                    for index, code in enumerate(codes):
                        name = f'code{index}'
                        names.append(':' + name)
                        params[name] = code
                    predicates.append('LEFT(unified_code,6) IN (' + ','.join(names) + ')')
                records = conn.execution_options(stream_results=True).execute(text(
                    f'SELECT RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code,report_date,payload FROM {plugin.table} WHERE ' + ' AND '.join(predicates) +
                    ' ORDER BY unified_code,report_date'), params).mappings()
                try:
                    for unit, group in groupby(records, lambda r: r['market'] + ':' + r['code']):
                        if unit not in missing:
                            for _ in group:
                                pass
                            continue
                        missing.remove(unit)
                        raw_rows = list(group)
                        rows = [json.loads(r['payload']) if isinstance(r['payload'], str) else r['payload']
                                for r in raw_rows]
                        sql_keys_match = all(str(raw['report_date']) == row['report_date']
                                             for raw, row in zip(raw_rows, rows, strict=True))
                        rows.sort(key=lambda r: r['report_date'], reverse=True)
                        proof = state.get('units', {}).get(unit, {})
                        wanted = [d for d in proof.get('dates', []) if scope.includes(d)]
                        matched = (sql_keys_match and digest(rows) == proof.get('digest')
                                   and [r['report_date'] for r in rows] == proof.get('dates', []))
                        full_rows = rows
                        findings['cache_plan'][unit] = dict(
                            hash=digest({'rows': full_rows, 'manifest': None}), observed=proof.get('observed_at'))
                        rows = [r for r in rows if scope.includes(r['report_date'])]
                        try:
                            validate_rows(plugin.kind, unit, full_rows)
                        except (ValueError, TypeError, KeyError) as exc:
                            matched = False
                            if len(findings['coverage']) < 100:
                                findings['coverage'].append(dict(code=unit, report_date='', message=str(exc)))
                        complete &= matched and bool(wanted)
                        findings['integrity_ok'] &= matched
                        if not wanted and len(findings['coverage']) < 100:
                            findings['scope_unavailable'] = True
                            findings['coverage'].append(dict(code=unit, report_date='', message='来源在所选范围未返回报告期；不能当成漏采，也不能宣称此范围可用'))
                        if not matched and len(findings['coverage']) < 100:
                            findings['coverage'].append(dict(code=unit, report_date='', message='来源报告期集合或内容摘要不匹配'))
                        count += len(rows)
                        rolling = chain(rolling, unit, rows)
                        if proof.get('observed_at'):
                            observed.append(datetime.fromisoformat(proof['observed_at']))
                        for row in rows:
                            for issue in quality_issues(plugin.kind, row):
                                findings[issue['criterion']] += 1
                                if sum(x['criterion'] == issue['criterion'] for x in findings['details']) < 100:
                                    findings['details'].append(dict(code=unit, report_date=row['report_date'], **issue))
                                if len(findings['examples']) < 5:
                                    findings['examples'].append(f"{unit} {row['report_date']} {issue['message']}")
                finally:
                    records.close()
            for unit in sorted(missing):
                complete = False
                findings['integrity_ok'] = False
                if len(findings['coverage']) < 100:
                    findings['coverage'].append(dict(code=unit, report_date='', message='指定范围无已归档报告；不能推断来源不存在'))
            for code in sorted(unknown_codes):
                if len(findings['coverage']) < 100:
                    findings['coverage'].append(dict(code=code, report_date='', message='不在当前股票池，范围无法核验'))
            actual = dict(units=len(keys), count=count, scope_hash=digest(keys), digest=rolling)
            manifest = state.get('manifest', {})
            if not scope.codes and not scope.start and not scope.end:
                manifest_matches = all(manifest.get(k) == v for k, v in actual.items())
                complete &= manifest_matches
                findings['manifest_mismatch'] = not manifest_matches
                if not manifest_matches and len(findings['coverage']) < 100:
                    findings['coverage'].append(dict(code='', report_date='', message='整轮集合证明与当前内容不匹配，不能宣称本轮完整'))
                stamp = manifest.get('observed_at')
                last = datetime.fromisoformat(stamp) if stamp else None
            else:
                last = min(observed) if keys and len(observed) == len(keys) else None
            fresh = bool(last and datetime.now(UTC) - timedelta(days=3) <= last <= datetime.now(UTC))
            return complete, fresh, count, actual, last, findings
