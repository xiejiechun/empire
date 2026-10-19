"""Atomic typed market storage used by archive, browsing and explicit maintenance."""
from sqlalchemy import text

from empire.features.kaipanla.codec import decode, encode, key_set
from empire.features.kaipanla.storage_contract import LAYOUT_VERSION, SERIES, dataset_tables


def params(kind, security, day):
    return dict(kind=kind, unified_code=security, trade_date=day)


def head_record(conn, kind, security, day, *, prefix='', lock=False):
    return conn.execute(text(f'SELECT * FROM {prefix}stock_market_day WHERE kind=:kind '
        'AND unified_code=:unified_code AND trade_date=:trade_date' + (' FOR UPDATE' if lock else '')),
        params(kind, security, day)).mappings().first()


def fact_records(conn, head, *, prefix=''):
    records = {}
    for table in dataset_tables(head['kind'])[1:]:
        order = 'block_seq' if head['kind'] == 'trades' else 'seq' if head['kind'] in SERIES else ('side,level' if table.endswith('_level') else 'unified_code')
        records[table] = [dict(r) for r in conn.execute(text(f'SELECT * FROM {prefix}{table} '
            f'WHERE unified_code=:unified_code AND trade_date=:trade_date ORDER BY {order} LIMIT 100001'), head).mappings()]
    return records


def read_day(conn, head, *, prefix='', facts=None):
    from empire.features.kaipanla.normalization import digest, point_count, validate
    row = decode(head, facts if facts is not None else fact_records(conn, head, prefix=prefix))
    validate(row, head['kind'], storage_check=False)
    if (point_count(row) != head['point_count'] or head['contract_version'] != LAYOUT_VERSION or digest(row) != head['content_hash']
            or key_set(row) != head['key_set_hash']):
        raise ValueError('证券日内容或校验证明不匹配')
    return row


def insert_rows(conn, table, rows):
    if not rows:
        return
    columns = list(rows[0])
    conn.execute(text(f'INSERT INTO {table} (' + ','.join('`'+c+'`' for c in columns) + ') VALUES (' +
        ','.join(':'+c for c in columns) + ')'), rows)


def row_key(table, row):
    if table.endswith('_block'):
        return row['block_seq']
    if table.endswith('_level'):
        return row['side'], row['level']
    if any(table.endswith(SERIES[k][0]) for k in ('trend', 'volume', 'entrust', 'large_order')):
        from empire.features.kaipanla.codec import clock
        return clock(row['source_time'])
    return row.get('seq', 0)


def synchronize(conn, table, old, new):
    previous = {row_key(table, r): r for r in old}
    incoming = {row_key(table, r): r for r in new}
    inserts, updates, deletes = [], [], []
    for key, row in incoming.items():
        prior = previous.get(key)
        # SQL TIME values decode as timedelta; normalize before comparing.
        if prior and 'source_time' in prior:
            from empire.features.kaipanla.codec import clock
            prior = {**prior, 'source_time': clock(prior['source_time'], len(row['source_time']) == 8)}
        if prior and table.endswith('_block'):
            from empire.features.kaipanla.codec import clock
            prior = {**prior, **{k: clock(prior[k], True) for k in ('first_time', 'last_time')}}
        if prior is None:
            inserts.append(row)
        else:
            dirty = tuple(c for c, v in row.items() if prior[c] != v)
            if dirty:
                updates.append((row, dirty))
    deletes = [row for key, row in previous.items() if key not in incoming]
    identity = ['unified_code', 'trade_date'] + (['block_seq'] if table.endswith('_block') else ['side', 'level'] if table.endswith('_level') else
                ['source_time'] if table in {SERIES[k][0] for k in ('trend', 'volume', 'entrust', 'large_order')}
                else ['seq'] if 'seq' in (new[0] if new else old[0]) else [])
    where = ' AND '.join('`'+c+'`=:'+c for c in identity)
    if deletes:
        conn.execute(text(f'DELETE FROM {table} WHERE '+where), deletes)
    if updates:
        groups = {}
        for row, dirty in updates:
            columns = tuple(c for c in dirty if c not in identity)
            groups.setdefault(columns, []).append(row)
        for columns, records in groups.items():
            conn.execute(text(f'UPDATE {table} SET '+','.join('`'+c+'`=:'+c for c in columns)+' WHERE '+where), records)
    insert_rows(conn, table, inserts)
    return len(inserts) + len(updates) + len(deletes)


def write_day(conn, row, checksum, observed, *, prefix='', compare=True):
    from datetime import date
    old = head_record(conn, row['kind'], row['code']+'.'+row['market'],
                      date.fromisoformat(row['trade_date']), prefix=prefix, lock=True) if compare else None
    if old and observed < old['version_observed_at']:
        return False, 0
    if old:
        prior_facts = fact_records(conn, old, prefix=prefix)
        try:
            prior = read_day(conn, old, prefix=prefix, facts=prior_facts)
        except (ValueError, KeyError, TypeError):
            # A new validated observation repairs invalid formal content. Version
            # ordering above still prevents an older response from doing so.
            prior = None
        from empire.features.kaipanla.normalization import business_content
        if prior is not None and business_content(prior) == business_content(row):
            return True, 0
    else:
        prior_facts = {}
    head, facts = encode(row, checksum, observed)
    if not old and compare:
        # A missing head cannot certify orphaned facts. Reconcile them against
        # the new complete validated unit rather than repeatedly failing INSERT.
        prior_facts = fact_records(conn, head, prefix=prefix)
    changed = 0
    for table, records in facts.items():
        existing = prior_facts.get(table, [])
        changed += synchronize(conn, prefix+table, existing, records) if existing else len(records)
        if not existing:
            insert_rows(conn, prefix+table, records)
    if old:
        import json

        from empire.features.kaipanla.codec import obj
        def value(column, raw):
            return json.dumps(obj(raw), sort_keys=True, ensure_ascii=False) if column in (
                'identity_extra', 'product_extra', 'source_metadata') else raw
        columns = [c for c in head if c not in ('kind', 'unified_code', 'trade_date')
                   and value(c, head[c]) != value(c, old[c])]
        if columns:
            conn.execute(text(f'UPDATE {prefix}stock_market_day SET '+','.join('`'+c+'`=:'+c for c in columns)+
                ' WHERE kind=:kind AND unified_code=:unified_code AND trade_date=:trade_date'), head)
        head_changed = bool(columns)
    else:
        insert_rows(conn, prefix+'stock_market_day', [head])
        head_changed = True
    return True, changed + int(head_changed)
