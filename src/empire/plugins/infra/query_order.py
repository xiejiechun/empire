"""Bounded SQL ordering for formal queries, with null-last keyset pagination.

Relations and field expressions are owned by the calling feature. User input
selects a registered field, never an SQL expression. The relation must contain
the entire filtered set, before ORDER BY or LIMIT.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def _wire(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
    if isinstance(value, Decimal):
        return str(value)
    return value


def ordered_page(conn, relation, params, *, order, fields, identity, after=None, limit=50):
    """Return a query-bound page: limit+1 sort keys, then at most limit bodies.

    fields maps public names to trusted expressions against the relation alias
    q. identity names nonnullable, uniquely identifying columns in that relation.
    Changes to data between requests are not a repeatable-read snapshot.
    """
    if (not isinstance(order, dict) or set(order) != {'field', 'direction'}
            or order.get('field') not in fields or order.get('direction') not in ('asc', 'desc')):
        raise ValueError('排序字段或方向无效')
    if type(limit) is not int or not 1 <= limit <= 500 or not identity:
        raise ValueError('排序分页上限或业务身份无效')
    expression = fields[order['field']]
    expression = f"CASE WHEN CAST(({expression}) AS CHAR)='' THEN NULL ELSE ({expression}) END"
    signature = hashlib.sha256(json.dumps(
        [relation, params, order, identity, expression], default=_wire,
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode()).hexdigest()
    args = dict(params)
    # Projection aliases also keep JSON and computed values in their SQL type.
    selected = ('SELECT ' + ','.join(f'q.`{key}`' for key in identity)
                + f', {expression} AS __order_value FROM ({relation}) q')
    terms = ['(__order_value IS NULL) ASC', '__order_value ' + order['direction'].upper()]
    terms.extend(f'`{key}` ASC' for key in identity)
    condition = ''
    if after is not None:
        if (not isinstance(after, dict) or set(after) != {'query', 'value', 'keys', 'decimal'}
                or after['query'] != signature or not isinstance(after['keys'], list)
                or type(after['decimal']) is not bool
                or len(after['keys']) != len(identity) or any(v is None for v in after['keys'])):
            raise ValueError('排序游标不属于当前查询，请返回第一页')
        ties, equal = [], []
        for i, key in enumerate(identity):
            name = f'__seek_key_{i}'
            args[name] = after['keys'][i]
            ties.append('(' + ' AND '.join([*equal, f'`{key}` > :{name}']) + ')')
            equal.append(f'`{key}` = :{name}')
        tie = '(' + ' OR '.join(ties) + ')'
        if after['value'] is None:
            condition = ' WHERE __order_value IS NULL AND ' + tie
        else:
            args['__seek_value'] = after['value']
            op = '>' if order['direction'] == 'asc' else '<'
            # MySQL compares a DECIMAL to a bound string as DOUBLE unless the
            # parameter is explicitly typed. That loses digits and repeats rows.
            bound = 'CAST(:__seek_value AS DECIMAL(65,30))' if after['decimal'] else ':__seek_value'
            condition = (f' WHERE (__order_value IS NULL OR __order_value {op} {bound} '
                         f'OR (__order_value = {bound} AND {tie}))')
    args['__page_limit'] = limit + 1
    sql = ('SELECT /*+ MAX_EXECUTION_TIME(15000) SET_VAR(max_sort_length=1048576) '
           'SET_VAR(sort_buffer_size=33554432) */ * FROM (' + selected + ') ordered_rows'
           + condition + ' ORDER BY ' + ','.join(terms) + ' LIMIT :__page_limit')
    try:
        records = [dict(row) for row in conn.execute(text(sql), args).mappings()]
    except DBAPIError as exc:
        if getattr(exc.orig, 'args', (None,))[0] in (1038, 3024):
            raise ValueError('当前范围排序超过查询资源限制，请缩小日期或证券范围后重试') from None
        raise
    selected_rows = records[:limit]
    cursor = None
    if len(records) > limit:
        last = selected_rows[-1]
        cursor = dict(query=signature, value=_wire(last['__order_value']),
                      decimal=isinstance(last['__order_value'], Decimal),
                      keys=[_wire(last[key]) for key in identity])
    if not selected_rows:
        return [], None
    # Only identities and the sort value enter filesort. Large bodies are read
    # afterwards for this page, in the same connection/transaction snapshot.
    wanted, page_args, clauses = [], dict(params), []
    for i, row in enumerate(selected_rows):
        wanted.append(tuple(row[key] for key in identity))
        terms = []
        for j, key in enumerate(identity):
            name = f'__page_key_{i}_{j}'
            page_args[name] = row[key]
            terms.append(f'q.`{key}`=:{name}')
        clauses.append('(' + ' AND '.join(terms) + ')')
    fetch = ('SELECT /*+ MAX_EXECUTION_TIME(15000) */ q.* FROM (' + relation
             + ') q WHERE ' + ' OR '.join(clauses) + ' LIMIT :__page_limit')
    page_args['__page_limit'] = limit + 1
    by_key = {tuple(row[key] for key in identity): dict(row)
              for row in conn.execute(text(fetch), page_args).mappings()}
    if len(by_key) != len(wanted) or any(key not in by_key for key in wanted):
        raise ValueError('分页记录在读取期间变化，请返回第一页重新查询')
    return [by_key[key] for key in wanted], cursor


def column_fields(names):
    """Build a whitelist from a feature's existing field contract."""
    import re

    if any(not re.fullmatch(r'[a-z][a-z0-9_]*', name) for name in names):
        raise ValueError('查询字段登记无效')
    return {name: f'q.`{name}`' for name in names}

