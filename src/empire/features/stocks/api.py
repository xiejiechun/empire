"""Business-owned stocks.api."""
import json

from sqlalchemy import text


def current_directory(connection, namespace, *, lock=False):
    records = connection.execute(text('SELECT source,payload FROM collection_state '
        'WHERE namespace=:namespace AND dataset=\'stocks\' '
        'AND source IN (\'sina\',\'ths\')' + (' FOR UPDATE' if lock else '')),
        {'namespace': namespace}).mappings().all()
    values = []
    for row in records:
        value = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        if value.get('version'):
            values.append({**value, 'source': row['source']})
    return max(values, key=lambda item: item['version'], default={})
