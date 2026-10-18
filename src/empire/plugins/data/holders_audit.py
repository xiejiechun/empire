"""Read-only, bounded proof checks for the selected holder securities."""
from datetime import UTC, datetime

from sqlalchemy import text

from empire.contracts.holders import (
    KINDS,
    digest,
    quality_details,
    report_key,
    validate,
    validate_gaps,
)
from empire.plugins.datasets.holders import read_reports


def rows_for(conn, keys):
    rows = []
    for pos in range(0, len(keys), 10):
        rows.extend(read_reports(conn, keys[pos:pos + 10]))
    return sorted(rows, key=lambda r: (r['report_date'], r['instrument_key'], r['report_type']))


def unit_gaps(unit):
    gaps = validate_gaps(unit.get('source_gaps', []))
    if (gaps or 'source_gaps_digest' in unit) and unit.get('source_gaps_digest') != digest(gaps):
        raise ValueError('来源缺口集合与摘要不符')
    return gaps


def check_proof(kind, security, proof, rows, version, gaps=None):
    validate(kind, security, rows)
    stamp = version.key([proof['observed_at']], now=datetime.now(UTC))[0]
    if (proof.get('contract') != 4 or type(proof.get('count')) is not int or
            proof['count'] != len(rows) or proof.get('digest') != digest(rows) or
            proof.get('report_keys') != [report_key(r) for r in rows] or
            proof.get('availability') != ('source_gap' if gaps else 'available' if rows else 'not_published')):
        raise ValueError('证券栏目证明与实际报告集合不符')
    return stamp


def audit_units(conn, state, kind, scope, version):
    current = [r[0] for r in conn.execute(text('SELECT unified_code FROM stock ORDER BY unified_code LIMIT 15001'))]
    units = state.get('units', {})
    if len(current) > 15000 or len(units) > 15000:
        raise ValueError('持有人审计范围超限')
    selected = [key for key in current if not scope.codes or key[:6] in scope.codes]
    missing_codes = set(scope.codes) - {key[:6] for key in selected}
    result = dict(complete=False, reports=0, not_published=0, notices=0, rank_gaps=0,
                  quality_counts={}, stamps={}, digests={}, missing=0, findings=[], securities=len(selected))
    def missing(key, reason):
        result['missing'] += 1
        if len(result['findings']) < 100:
            result['findings'].append(dict(security=key, message=reason))
    for code in sorted(missing_codes):
        missing(code, '所选证券不在当前股票池，不能确认来源窗口')
    expected_count = sum(len(units.get(key, {}).get('kinds', {}).get(kind, {}).get('report_keys', [])) for key in selected)
    if expected_count > 100000:
        raise ValueError('持有人正文审计超过十万报告边界')
    for offset in range(0, len(selected), 20):
        group = selected[offset:offset + 20]
        actual = {key: units.get(key, {}).get('kinds', {}).get(kind, {}).get('report_keys', []) for key in group}
        eligible = []
        for key in group:
            proof = units.get(key, {}).get('kinds', {}).get(kind, {})
            if state.get('contract_version') != 4 or not proof:
                missing(key, '缺少现行证券栏目归档证明')
            else:
                eligible.append(key)
        try:
            indexed = {report_key(r): r for r in rows_for(conn, [k for key in eligible for k in actual[key]])}
        except (ValueError, KeyError, TypeError):
            indexed = None  # Locate corruption per issuer without hiding the other issuers.
        for key in eligible:
            try:
                rows = rows_for(conn, actual[key]) if indexed is None else [indexed[k] for k in actual[key]]
                proof = units[key]['kinds'][kind]
                gaps = unit_gaps(units[key])
                relevant = [g for g in gaps if g['kind'] == kind]
                stamp = check_proof(kind, key, proof, rows, version, relevant)
            except (ValueError, KeyError, TypeError) as exc:
                missing(key, str(exc))
                continue
            result['stamps'][key] = stamp
            result['digests'][key] = proof['digest']
            result['not_published'] += not rows and not relevant
            if relevant:
                missing(key, '债券名称为空，未识别报告保留来源缺口：' +
                        '、'.join(g['report_date'] + '（' + g['source_panel'] + '）' for g in relevant))
            for row in rows:
                if not scope.includes(row['report_date']):
                    continue
                result['reports'] += 1
                result['notices'] += row['report_type'] == 'change_notice'
                ranks = [m['source_rank'] or m['seq'] for m in row['members'] if m['member_group'] == 'current']
                result['rank_gaps'] += ranks != list(range(1, len(ranks) + 1))
                for issue in quality_details(row):
                    reason = issue['reason']
                    result['quality_counts'][reason] = result['quality_counts'].get(reason, 0) + 1
    result['complete'] = bool(selected) and not result['missing']
    result['findings'] = tuple(result['findings'])
    return result


def cache_hashes(conn, state, expectations, audited_kind, version):
    """Optional hot confirmations require the entire three-column SQL payload."""
    hashes = {}
    if len(expectations) > 15000:
        raise ValueError('持有人缓存核对范围超限')
    for key, expected in expectations.items():
        unit = state.get('units', {}).get(key, {})
        reports = {}
        if unit.get('kinds', {}).get(audited_kind, {}).get('digest') != expected:
            continue  # A concurrent revision cannot refresh the older audited content.
        try:
            gaps = unit_gaps(unit)
            for kind in KINDS:
                proof = unit['kinds'][kind]
                identities = proof['report_keys']
                if not isinstance(identities, list) or len(identities) > 100000:
                    raise ValueError('证券缓存正文集合超限')
                reports[kind] = rows_for(conn, identities)
                check_proof(kind, key, proof, reports[kind], version, [g for g in gaps if g['kind'] == kind])
            if unit.get('contract') != 4 or unit.get('digest') != digest(reports):
                raise ValueError('证券整体证明不符')
            content = dict(reports=reports, manifest=None)
            if gaps:
                content['gaps'] = gaps
            hashes[key] = digest(content)
        except (ValueError, KeyError, TypeError):
            continue
    return hashes
