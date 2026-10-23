"""Single typed SQL read/write path for latest theme detail and daily lists."""
from sqlalchemy import text

from empire.contracts.security import split_unified_code
from empire.core.time import mysql_time
from empire.features.themes.history_model import digest
from empire.features.themes.storage_contract import (
    CATEGORY_FIELDS,
    DAILY_FIELDS,
    HEAD_FIELDS,
    RELATION_FIELDS,
    STOCK_FIELDS,
    TIME_FIELDS,
    daily_record,
    decode_daily,
    epoch,
    source_time,
    validate_detail,
)

REASON_COLUMNS = tuple('unified_code' if k == 'source_stock_id' else k for k in RELATION_FIELDS)
TABLE_COLUMNS = {
    'theme_daily': ('business_date', *DAILY_FIELDS, 'observed_at'),
    'theme_detail': (*HEAD_FIELDS, 'observed_at', 'content_sha256'),
    'theme_category': ('theme_id', *CATEGORY_FIELDS),
    'theme_stock': ('theme_id', *STOCK_FIELDS),
    'theme_stock_reason': ('theme_id', *REASON_COLUMNS),
}
CHILDREN = (('categories', 'theme_category', CATEGORY_FIELDS, 'category_id', 5000),
            ('stocks', 'theme_stock', STOCK_FIELDS, 'source_stock_id', 10000),
            ('relations', 'theme_stock_reason', RELATION_FIELDS, 'relation_id', 50000))


def _columns(names):
    return ','.join('`' + k + '`' for k in names)


def _decode(record, fields):
    return {k: epoch(record[k]) if k in TIME_FIELDS else record[k] for k in fields}


def read_detail_head(conn, theme_id, *, lock=False):
    ending = ' FOR UPDATE' if lock else ''
    return conn.execute(text('SELECT theme_id,source_updated_at,observed_at,content_sha256 '
                             'FROM theme_detail WHERE theme_id=:id' + ending),
                        {'id': theme_id}).mappings().one_or_none()


def read_detail(conn, theme_id, *, lock=False):
    ending = ' FOR UPDATE' if lock else ''
    head = conn.execute(text('SELECT * FROM theme_detail WHERE theme_id=:id' + ending),
                        {'id': theme_id}).mappings().one_or_none()
    if head is None:
        return None, None
    result = _decode(head, HEAD_FIELDS)
    for name, table, fields, key, limit in CHILDREN:
        order = 'order' if name == 'categories' else key
        columns = REASON_COLUMNS if name == 'relations' else fields
        records = conn.execute(text(f'SELECT {_columns(columns)} FROM {table} WHERE theme_id=:id '
                                    f'ORDER BY `{order}` LIMIT :limit' + ending),
                               {'id': theme_id, 'limit': limit + 1}).mappings().all()
        if len(records) > limit:
            raise ValueError('正式题材子表超限')
        decoded = [_decode(r, columns) for r in records]
        if name == 'relations':
            for row in decoded:
                _, row['source_stock_id'] = split_unified_code(row.pop('unified_code'))
        result[name] = decoded
    return head, result


def _upsert(conn, table, names, keys, values):
    if not values:
        return
    sql = (f'INSERT INTO {table}({_columns(names)}) VALUES('
           + ','.join(':' + k for k in names) + ') ON DUPLICATE KEY UPDATE '
           + ','.join(f'`{k}`=VALUES(`{k}`)' for k in names if k not in keys))
    conn.execute(text(sql), values)


def _sql_row(row):
    return {k: source_time(v) if k in TIME_FIELDS else v for k, v in row.items()}


def replace_detail(conn, data, observed):
    """Caller owns transaction and old-version check; identical rows incur no DML."""
    validate_detail(data)
    theme_id = data['theme_id']
    head, previous = read_detail(conn, theme_id, lock=True)
    fingerprint = digest(data)
    changes = 0
    if previous == data and head['content_sha256'] == fingerprint:
        return 0
    for name, table, fields, key, _ in CHILDREN:
        old = {r[key]: r for r in previous[name]} if previous else {}
        new = {r[key]: r for r in data[name]}
        changed = [dict(theme_id=theme_id, **_sql_row(row)) for k, row in new.items() if old.get(k) != row]
        if name == 'relations':
            mapping = {s['source_stock_id']: s['unified_code'] for s in data['stocks']}
            for row in changed:
                row['unified_code'] = mapping[row.pop('source_stock_id')]
        _upsert(conn, table, TABLE_COLUMNS[table], ('theme_id', key), changed)
        removed = old.keys() - new.keys()
        if removed:
            conn.execute(text(f'DELETE FROM {table} WHERE theme_id=:id AND `{key}`=:key'),
                         [{'id': theme_id, 'key': k} for k in sorted(removed)])
        changes += len(changed) + len(removed)
    values = _sql_row({k: data[k] for k in HEAD_FIELDS})
    values.update(observed_at=mysql_time(observed), content_sha256=fingerprint)
    _upsert(conn, 'theme_detail', TABLE_COLUMNS['theme_detail'], ('theme_id',), [values])
    return changes + 1


def read_daily(conn, day, *, lock=False):
    records = conn.execute(text('SELECT * FROM theme_daily WHERE business_date=:day '
                               'ORDER BY theme_id LIMIT 2001' + (' FOR UPDATE' if lock else '')),
                           {'day': day}).mappings().all()
    if len(records) > 2000:
        raise ValueError('正式每日题材目录超限')
    return records, [decode_daily(r) for r in records]


def replace_daily(conn, day, rows, observed):
    _, before = read_daily(conn, day, lock=True)
    old, new = ({r['theme_id']: r for r in items} for items in (before, rows))
    changed = [daily_record(row, day, observed) for key, row in new.items() if old.get(key) != row]
    _upsert(conn, 'theme_daily', TABLE_COLUMNS['theme_daily'], ('business_date', 'theme_id'), changed)
    removed = old.keys() - new.keys()
    if removed:
        conn.execute(text('DELETE FROM theme_daily WHERE business_date=:day AND theme_id=:id'),
                     [{'day': day, 'id': key} for key in sorted(removed)])
    return len(changed) + len(removed)
