"""Typed SQL mutations only for changed source facts, within caller transaction."""
from datetime import datetime

from sqlalchemy import text

from empire.core.time import CHINA, mysql_time
from empire.features.yuanhang_limits.contract import (
    DECIMAL_FIELDS,
    MEMBER_FIELDS,
    TABLE_COLUMNS,
    TIME_FIELDS,
)
from empire.features.yuanhang_limits.model import decimal_value, digest
from empire.features.yuanhang_limits.storage import pool_proof


def columns(names):
    return ','.join('`' + name + '`' for name in names)


def read_pool_head(conn, day, pool, *, lock=False):
    return conn.execute(text('SELECT * FROM yuanhang_limit_pool WHERE trade_date=:day '
                             'AND pool_type=:pool' + (' FOR UPDATE' if lock else '')),
                        dict(day=day, pool=pool)).mappings().one_or_none()


def decode_member(row):
    result = {k: row[k] for k in MEMBER_FIELDS}
    for key in DECIMAL_FIELDS:
        result[key] = decimal_value(result[key], key)
    for key in TIME_FIELDS:
        if result[key] is not None:
            result[key] = int(result[key].replace(tzinfo=CHINA).timestamp())
    return result


def read_members(conn, day, pool):
    rows = conn.execute(text('SELECT ' + columns(MEMBER_FIELDS) + ' FROM yuanhang_limit_member '
        'WHERE trade_date=:day AND pool_type=:pool ORDER BY unified_code LIMIT 10001'),
        dict(day=day, pool=pool)).mappings().all()
    if len(rows) > 10000:
        raise ValueError('日期池SQL成员超限')
    return [decode_member(row) for row in rows]


def upsert(conn, table, keys, rows):
    if not rows:
        return
    names = TABLE_COLUMNS[table]
    sql = 'INSERT INTO ' + table + '(' + columns(names) + ') VALUES(' + ','.join(':' + k for k in names)
    sql += ') ON DUPLICATE KEY UPDATE ' + ','.join('`' + k + '`=VALUES(`' + k + '`)' for k in names if k not in keys)
    for offset in range(0, len(rows), 200):
        conn.execute(text(sql), rows[offset:offset + 200])


def replace_pool(conn, value, observed, head):
    day, pool = value['trade_date'], value['pool_type']
    old = {r['unified_code']: r for r in read_members(conn, day, pool)}
    new = {r['unified_code']: r for r in value['rows']}
    proof = pool_proof(value)
    if old == new and head and all(head[k] == v for k, v in proof.items()):
        return 0
    changed = []
    for key, row in new.items():
        if old.get(key) != row:
            data = dict(trade_date=day, pool_type=pool, **row)
            for field in TIME_FIELDS:
                if data[field] is not None:
                    data[field] = datetime.fromtimestamp(data[field], CHINA).replace(tzinfo=None)
            changed.append(data)
    upsert(conn, 'yuanhang_limit_member', ('trade_date', 'pool_type', 'unified_code'), changed)
    removed = sorted(old.keys() - new.keys())
    for offset in range(0, len(removed), 200):
        conn.execute(text('DELETE FROM yuanhang_limit_member WHERE trade_date=:day '
                          'AND pool_type=:pool AND unified_code=:code'),
                     [dict(day=day, pool=pool, code=k) for k in removed[offset:offset + 200]])
    upsert(conn, 'yuanhang_limit_pool', ('trade_date', 'pool_type'),
           [dict(trade_date=day, pool_type=pool, **proof, observed_at=mysql_time(observed))])
    return len(changed) + len(removed) + 1


def read_reason(conn, day, code, *, lock=False):
    return conn.execute(text('SELECT * FROM yuanhang_limit_reason WHERE trade_date=:day '
                             'AND unified_code=:code' + (' FOR UPDATE' if lock else '')),
                        dict(day=day, code=code)).mappings().one_or_none()


def replace_reason(conn, value, observed, previous):
    fingerprint = digest(value)
    if previous and previous['content_sha256'] == fingerprint:
        before = {k: previous[k].isoformat() if k == 'trade_date' else previous[k] for k in value}
        if before == value:
            return 0
    upsert(conn, 'yuanhang_limit_reason', ('trade_date', 'unified_code'),
           [dict(value, content_sha256=fingerprint, observed_at=mysql_time(observed))])
    return 1
