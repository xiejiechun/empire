"""Reviewed schema shapes: runtime checks types, indexes and CHECK constraints, never DDL."""
import json
import re

from sqlalchemy import inspect

from empire.contracts.market_storage import MARKET_TABLES
from empire.core.config import resource_root


def manifest():
    return json.loads((resource_root() / 'sql/schema-contract.json').read_text('utf-8'))


def market_contract():
    shapes = manifest()['tables']
    return ({t: set(shapes[t]['columns']) for t in MARKET_TABLES},
            {t: shapes[t]['primary'] for t in MARKET_TABLES})


def normalize_check(value):
    return re.sub(r'\s+|`|_utf8mb4|_ascii', '', value.lower())


def shape(conn, table):
    meta = inspect(conn)
    columns = {r['name']: {'type': str(r['type']).lower(), 'nullable': r['nullable'], 'unsigned': bool(getattr(r['type'], 'unsigned', False))}
               for r in meta.get_columns(table)}
    indexes = {r['name']: {'columns': r.get('column_names'), 'expressions': r.get('expressions'),
                          'unique': bool(r['unique'])} for r in meta.get_indexes(table)}
    checks = {r['name']: normalize_check(r['sqltext']) for r in meta.get_check_constraints(table)}
    return dict(columns=columns, primary=meta.get_pk_constraint(table)['constrained_columns'],
                indexes=indexes, checks=checks)


def validate_shapes(conn, tables):
    expected = manifest()['tables']
    for table in tables:
        if table in expected and shape(conn, table) != expected[table]:
            raise RuntimeError(f'表 {table} 类型、空值、索引或约束与正式契约不符；须显式维护')
