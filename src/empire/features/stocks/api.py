"""Business-owned stocks.api."""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

# collection_state.payload remains a heterogeneous persisted business payload.
# This alias does not assert that JSON fields have passed publication validation.
type DirectoryPayload = dict[str, Any]


def current_directory(
    connection: Connection, namespace: str, *, lock: bool = False,
) -> DirectoryPayload:
    records = connection.execute(text('SELECT source,payload FROM collection_state '
        'WHERE namespace=:namespace AND dataset=\'stocks\' '
        'AND source IN (\'sina\',\'ths\')' + (' FOR UPDATE' if lock else '')),
        {'namespace': namespace}).mappings().all()
    values: list[DirectoryPayload] = []
    for row in records:
        value = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        if value.get('version'):
            values.append({**value, 'source': row['source']})
    return max(values, key=lambda item: item['version'], default={})
