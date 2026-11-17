"""Read date-pool confirmations from the single registered project."""
import json

from sqlalchemy import text

from empire.features.yuanhang_limits.contract import SOURCE, project


def pool_versions(conn, namespace, pool, days=None):
    params = dict(namespace=namespace, source=SOURCE, project=project(pool))
    expression = "JSON_EXTRACT(payload,'$.versions')"
    if days is not None:
        if not days:
            return {}
        fields = []
        for i, day in enumerate(days):
            params[f'd{i}'], params[f'p{i}'] = day, '$.versions."' + day + '"'
            fields.append(f':d{i},JSON_EXTRACT(payload,:p{i})')
        expression = 'JSON_OBJECT(' + ','.join(fields) + ')'
    raw = conn.execute(text('SELECT ' + expression + ' FROM collection_state '
        'WHERE namespace=:namespace AND source=:source AND project_id=:project'),
        params).scalar_one_or_none()
    values = json.loads(raw) if isinstance(raw, str) else raw or {}
    return {k: v for k, v in values.items() if v is not None}
