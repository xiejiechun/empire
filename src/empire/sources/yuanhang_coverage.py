"""Annual proof construction and content audit for native daily history.

No database or cache access here: callers supply the formal query's complete
annual rows. A count or latest trading date alone is never a passing audit.
"""
from empire.sources.yuanhang_payload import (
    CONTRACT,
    action_key,
    digest,
    validate_financial,
    validate_year,
)


def year_proof(payload):
    p = validate_year(payload)
    rows = p['rows']
    return dict(quote_year=p['year'], native_market=p['native_market'],
                source_count=p['source_count'], row_count=len(rows),
                first_date=rows[0][0] if rows else None,
                last_date=rows[-1][0] if rows else None,
                key_hash=p['key_hash'], content_hash=digest(rows),
                contract_version=CONTRACT,
                verified_through=min(p['through'], f"{p['year']:04d}-12-31"))


def audit_year(payload, stored_rows, stored_proof):
    """Return explicit failures; do not bless a matching count with changed keys."""
    expected = year_proof(payload)
    problems = []
    if stored_proof is None:
        problems.append('missing_proof')
    # The SQL head records the cutoff at the last content change. A later
    # unchanged verification advances shared state/cache, without business DML.
    # Freshness is separate from this exact key/content audit.
    elif any(stored_proof.get(k) != v for k, v in expected.items() if k != 'verified_through'):
        problems.append('proof_mismatch')
    # Validation also rejects duplicate rows, noncanonical values and bad OHLC.
    try:
        candidate = {**payload, 'rows': stored_rows}
        validate_year(candidate)
    except (ValueError, TypeError, KeyError):
        problems.append('invalid_stored_rows')
    if stored_rows != payload['rows']:
        problems.append('content_mismatch')
    return problems


def financial_proofs(payload):
    p = validate_financial(payload)
    # Bind both facts to one validated 211 response, excluding request time.
    group = digest(p)
    proofs = {}
    for kind in ('actions', 'capital'):
        rows = p[kind]
        keys = [[r[0], action_key(r)] if kind == 'actions' else r[:2] for r in rows]
        dates = [r[0] if kind == 'actions' else r[1] for r in rows]
        proofs[kind] = dict(series_kind=kind, native_market=p['native_market'],
                            source_count=len(rows), row_count=len(rows),
                            first_date=min(dates) if dates else None,
                            last_date=max(dates) if dates else None,
                            key_hash=digest(keys), content_hash=digest(rows),
                            contract_version=CONTRACT, response_group=group)
    return proofs


def audit_financial(payload, stored_actions, stored_capital, stored_proofs):
    expected = financial_proofs(payload)
    problems = []
    for kind, proof in expected.items():
        actual = stored_proofs.get(kind)
        if actual is None or any(actual.get(k) != v for k, v in proof.items()):
            problems.append(kind + '_proof_mismatch')
    try:
        validate_financial({**payload, 'actions': stored_actions, 'capital': stored_capital})
    except (ValueError, TypeError, KeyError):
        problems.append('invalid_stored_rows')
    for kind, rows in (('actions', stored_actions), ('capital', stored_capital)):
        if rows != payload[kind]:
            problems.append(kind + '_content_mismatch')
    return problems
