"""Bounded SQL evidence for report-period maintenance and unchanged units."""
from datetime import UTC, datetime

from sqlalchemy import text

from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import digest, ordered, unit_key, validate_rows
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.tdx_maintenance import proofs_fresh, valid_proof


def periods_fresh(state, now):
    proofs = state.get('manifest', {}).get('periods', {})
    return (state.get('manifest', {}).get('period_scope_hash') == digest(sorted(proofs)) and
            proofs_fresh(proofs, now, lambda period: period >= f'{now.year - 1}-01-01'))


async def snapshot(query):
    def read():
        with query.mysql.read_engine.begin() as conn:
            state = read_state(conn, query.namespace, query.project_id, query.source)
            current = {unit_key(stock) for stock in query._securities(conn)}
            records = conn.execute(text('SELECT *,RIGHT(unified_code,2) AS market,'
                'LEFT(unified_code,6) AS code FROM dividend_plan LIMIT 100001')).mappings().all()
            if len(records) > 100000:
                raise ValueError('分红维护比较超过100000条安全上限')
            units = {}
            for record in records:
                row = decode(record)
                units.setdefault(unit_key(row), []).append(row)
            units = {key: ordered(rows) for key, rows in units.items()}
            now = datetime.now(UTC)
            valid = state.get('contract_version') == 3
            manifest = state.get('manifest', {})
            if manifest.get('periods'):
                valid &= manifest.get('period_scope_hash') == digest(sorted(manifest['periods']))
            for key, proof in state.get('units', {}).items():
                if key not in current:
                    continue  # Retired securities remain stored, outside this current-pool proof.
                rows = units.get(key, [])
                validate_rows('dividends', key, rows)
                valid &= bool(valid_proof(proof, now) and proof['count'] == len(rows)
                              and proof['digest'] == digest(rows))
            valid &= all(key in state.get('units', {}) for key in units if key in current)
            return state if valid else {}, units
    return await query.mysql.read(read)
