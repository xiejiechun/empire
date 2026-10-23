"""Bind capacity to complete owned table objects, including all dataset owners."""
import hashlib
import json
import re


def objects(schema, shapes, ownership, tables):
    statements = {m[1]: m[0] for m in re.finditer(
        r'CREATE TABLE IF NOT EXISTS (\w+)\s*\([\s\S]*?;', schema.replace('\r\n', '\n'))}
    result = {}
    for table in tables:
        owner = {k: ownership[k].get(table) for k in (
            'fixed_sources', 'primary_keys', 'source_overrides', 'required_columns')}
        owner.update(in_tables=table in ownership['tables'],
                     primary_exempt=table in ownership['primary_key_exemptions'], schema=ownership['schema'])
        owner['datasets'] = {k: {'tables': group, 'primary': ownership['dataset_tables'][k]}
                             for k, group in ownership['dataset_table_groups'].items() if table in group}
        result[table] = dict(ddl_sha256=hashlib.sha256(statements[table].encode()).hexdigest(),
                             shape=shapes['tables'][table], ownership=owner)
    return result


def verify(root, evidence, tables):
    expected = evidence.get('schema_objects')
    if not isinstance(expected, dict) or not set(tables) <= set(expected):
        raise ValueError('Capacity schema objects do not cover all owned tables')
    actual = objects((root / 'sql/schema.sql').read_text('utf-8'),
                     json.loads((root / 'sql/schema-contract.json').read_text('utf-8')),
                     json.loads((root / 'sql/business-schema.json').read_text('utf-8')), expected)
    if actual != expected:
        raise ValueError('Measured table DDL, physical shape or dataset ownership changed; remeasurement required')
