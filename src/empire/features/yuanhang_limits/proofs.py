"""Read date-pool confirmations from the single registered project."""
import json

from sqlalchemy import text

from empire.features.yuanhang_limits.contract import SOURCE, project


def pool_versions(conn, namespace, pool):
    raw = conn.execute(text("SELECT JSON_EXTRACT(payload,'$.versions') FROM collection_state "
        'WHERE namespace=:namespace AND source=:source AND project_id=:project'),
        dict(namespace=namespace, source=SOURCE, project=project(pool))).scalar_one_or_none()
    return json.loads(raw) if isinstance(raw, str) else raw or {}
