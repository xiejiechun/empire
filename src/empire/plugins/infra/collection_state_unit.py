"""Locked, bounded project-state access for datasets declaring security units."""
import json
import re
from datetime import UTC, datetime

from sqlalchemy import text

from empire.contracts.security import unit_identity
from empire.core.time import mysql_time

FIELDS = ('contract_version', 'progress', 'manifest')


def unit_path(unit):
    if isinstance(unit, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\|(SH|SZ|BJ)', unit):
        from datetime import date
        date.fromisoformat(unit[:10])
    elif isinstance(unit, str) and re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', unit):
        market = unit[-2:]
        unit_identity(market + ':' + unit[:6])
    else:
        unit_identity(unit)
    return '$.units.' + json.dumps(unit)


def decode(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def read_unit(connection, namespace, project_id, source, unit):
    paths = {field: '$.' + field for field in FIELDS}
    if unit != 'manifest':
        paths['unit'] = unit_path(unit)
    params = dict(namespace=namespace, project_id=project_id, **paths)
    projection = ','.join(f'JSON_EXTRACT(payload,:{field}) AS `{field}`' for field in paths)
    row = connection.execute(text('SELECT source,' + projection +
        ' FROM collection_state WHERE namespace=:namespace AND project_id=:project_id FOR UPDATE'),
        params).mappings().first()
    if row is None:
        return {}, False
    if row['source'] != source:
        raise ValueError('采集项目的来源与已归档状态不一致')
    previous = {field: decode(row[field]) for field in FIELDS if row[field] is not None}
    if unit != 'manifest' and row['unit'] is not None:
        previous['units'] = {unit: decode(row['unit'])}
    return previous, True


def save_unit(connection, namespace, project_id, source, dataset, unit, payload, previous, exists):
    if payload == previous:
        return
    allowed = set(FIELDS) | {'units'}
    if set(payload) - allowed or set(previous) - allowed:
        raise ValueError('单元状态包含未声明的项目字段')
    units = payload.get('units', {})
    if set(units) - ({unit} if unit != 'manifest' else set()):
        raise ValueError('单元状态不得更新其他证券')
    params = dict(namespace=namespace, project_id=project_id, source=source, dataset=dataset,
                  updated_at=mysql_time(datetime.now(UTC)))
    if not exists:
        connection.execute(text('INSERT INTO collection_state '
            '(namespace,project_id,source,dataset,payload,updated_at) '
            'VALUES(:namespace,:project_id,:source,:dataset,:payload,:updated_at)'),
            {**params, 'payload': json.dumps(payload, ensure_ascii=False, sort_keys=True)})
        return
    changes = [( '$.' + field, payload[field]) for field in FIELDS
               if field in payload and payload[field] != previous.get(field)]
    if unit in units and units[unit] != previous.get('units', {}).get(unit):
        # JSON_SET does not create a missing intermediate object.
        root = connection.execute(text('SELECT JSON_TYPE(JSON_EXTRACT(payload,\'$.units\')) '
            'FROM collection_state WHERE namespace=:namespace AND project_id=:project_id'), params).scalar_one()
        if root is None:
            changes.append(('$.units', {}))
        elif root != 'OBJECT':
            raise ValueError('项目 units 状态不是对象')
        changes.append((unit_path(unit), units[unit]))
    if not changes:
        return
    args = []
    for index, (path, value) in enumerate(changes):
        params[f'p{index}'], params[f'v{index}'] = path, json.dumps(value, ensure_ascii=False, sort_keys=True)
        args += [f':p{index}', f'CAST(:v{index} AS JSON)']
    connection.execute(text('UPDATE collection_state SET payload=JSON_SET(payload,' + ','.join(args) +
        '),dataset=:dataset,updated_at=:updated_at WHERE namespace=:namespace AND project_id=:project_id '
        'AND source=:source'), params)
