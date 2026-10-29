"""The single bounded typed SQL path, with changed-row-only replacement."""
from sqlalchemy import text

from empire.core.time import mysql_time
from empire.features.yuanhang.contract import TABLE_COLUMNS
from empire.sources.yuanhang_coverage import financial_proofs
from empire.sources.yuanhang_payload import ACTION_FIELDS, PRICE_FIELDS, action_key, number


def read_rows(conn, code, kind, *, year=None, lock=False):
    specs = {
        'prices': ('yuanhang_daily_price', ('trade_date', *PRICE_FIELDS), 366),
        'actions': ('yuanhang_corporate_action', ('ex_date', 'event_key', *ACTION_FIELDS), 2000),
        'capital': ('yuanhang_capital', ('capital_kind', 'effective_date', 'shares'), 30000),
    }
    table, fields, limit = specs[kind]
    params, where = dict(code=code), 'unified_code=:code'
    if kind == 'prices':
        if type(year) is not int or not 1900 <= year <= 2100:
            raise ValueError('远航版年度查询范围无效')
        where += ' AND trade_date BETWEEN :first AND :last'
        params.update(first=f'{year}-01-01', last=f'{year}-12-31')
    order = ','.join(fields[:2] if kind in ('capital', 'actions') else fields[:1])
    result = conn.execute(text(f'SELECT {",".join(fields)} FROM {table} WHERE {where} '
        f'ORDER BY {order} LIMIT {limit + 1}' + (' FOR UPDATE' if lock else '')), params).all()
    if len(result) > limit:
        raise ValueError('远航版正式业务单元超限')
    rows = []
    for r in result:
        if kind == 'capital':
            rows.append([r[0], r[1].isoformat(), number(r[2], nullable=r[0] == 'circulating')])
        elif kind == 'actions':
            row = [r[0].isoformat()] + [number(v, signed=k == 'bonus_ratio')
                for k, v in zip(ACTION_FIELDS, r[2:], strict=True)]
            if action_key(row) != r[1]:
                raise ValueError('远航版权息事件身份与分量不一致')
            rows.append(row)
        else:
            rows.append([r[0].isoformat()] + [number(v, nullable=fields[i+1] in ('volume_shares', 'amount_yuan'))
                                             for i, v in enumerate(r[1:])])
    return rows


def read_heads(conn, code, *, year=None, lock=False):
    table, key = ('yuanhang_price_year', 'quote_year') if year is not None else ('yuanhang_series_proof', 'series_kind')
    params, where = dict(code=code), 'unified_code=:code'
    if year is not None:
        where += ' AND quote_year=:year'
        params['year'] = year
    rows = conn.execute(text(f'SELECT * FROM {table} WHERE {where} ORDER BY {key} LIMIT 151'
                             + (' FOR UPDATE' if lock else '')), params).mappings().all()
    if len(rows) > (1 if year is not None else 2):
        raise ValueError('远航版来源证明超限')
    return {r[key]: {k: v.isoformat() if k in ('first_date', 'last_date', 'verified_through')
                    and v is not None else v for k, v in r.items()} for r in rows}


def _upsert(conn, table, keys, records):
    if not records:
        return
    fields = TABLE_COLUMNS[table]
    conn.execute(text(f'INSERT INTO {table} ({",".join(fields)}) VALUES ('
        + ','.join(':' + k for k in fields) + ') ON DUPLICATE KEY UPDATE '
        + ','.join(f'{k}=VALUES({k})' for k in fields if k not in keys)), records)


def _replace(conn, table, code, incoming, existing, fields, key_size):
    # Identifiers are exclusively module-owned; only values enter SQL parameters.
    old = {tuple(r[:key_size]): r for r in existing}
    new = {tuple(r[:key_size]): r for r in incoming}
    removed = [dict(unified_code=code, **dict(zip(fields[:key_size], k, strict=True)))
               for k in old.keys() - new.keys()]
    if removed:
        conn.execute(text(f'DELETE FROM {table} WHERE unified_code=:unified_code AND '
            + ' AND '.join(f'{k}=:{k}' for k in fields[:key_size])), removed)
    changed = [dict(unified_code=code, **dict(zip(fields, r, strict=True)))
               for k, r in new.items() if old.get(k) != r]
    _upsert(conn, table, ('unified_code', *fields[:key_size]), changed)
    return len(removed) + len(changed)


def _save_proof(conn, table, code, proof, old, observed):
    # Pure re-verification extends ordering in collection_state, without business DML.
    compared = {k: v for k, v in proof.items() if k != 'verified_through'}
    if old and all(old.get(k) == v for k, v in compared.items()):
        return 0
    keys = ('unified_code', 'quote_year' if table == 'yuanhang_price_year' else 'series_kind')
    _upsert(conn, table, keys, [dict(unified_code=code, **proof,
                                    version_observed_at=mysql_time(observed))])
    return 1


def replace_financial(conn, payload, observed, old_heads):
    code, count = payload['code'], 0
    for kind, table, fields, key_size in (
        ('actions', 'yuanhang_corporate_action', ('ex_date', 'event_key', *ACTION_FIELDS), 2),
        ('capital', 'yuanhang_capital', ('capital_kind', 'effective_date', 'shares'), 2),
    ):
        incoming, existing = payload[kind], read_rows(conn, code, kind, lock=True)
        if kind == 'actions':
            incoming = [[r[0], action_key(r), *r[1:]] for r in incoming]
            existing = [[r[0], action_key(r), *r[1:]] for r in existing]
        count += _replace(conn, table, code, incoming, existing, fields, key_size)
    for kind, proof in financial_proofs(payload).items():
        counts = {k + '_count': sum(r[0] == k for r in payload['capital']) if kind == 'capital' else 0
                  for k in ('total', 'circulating', 'free_float')}
        count += _save_proof(conn, 'yuanhang_series_proof', code, {**proof, **counts},
                             old_heads.get(kind), observed)
    return count
