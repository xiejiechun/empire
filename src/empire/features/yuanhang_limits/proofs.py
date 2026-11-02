"""Merge SQL confirmations from the registered owners of one date-pool dataset."""
import json

from sqlalchemy import bindparam, text

from empire.features.yuanhang_limits.contract import SOURCE, pool_projects


def pool_versions(conn, namespace, pool):
    statement = text("SELECT JSON_EXTRACT(payload,'$.versions') FROM collection_state "
        'WHERE namespace=:namespace AND source=:source AND project_id IN :projects').bindparams(
            bindparam('projects', expanding=True))
    result = {}
    for raw in conn.execute(statement, dict(namespace=namespace, source=SOURCE,
                                            projects=pool_projects(pool))).scalars():
        versions = json.loads(raw) if isinstance(raw, str) else raw or {}
        for day, version in versions.items():
            result[day] = max(result.get(day, ''), version)
    return result


def latest_pool_version(conn, namespace, pool, day):
    statement = text('SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,:path)) FROM collection_state '
        'WHERE namespace=:namespace AND source=:source AND project_id IN :projects').bindparams(
            bindparam('projects', expanding=True))
    return max((v for v in conn.execute(statement, dict(namespace=namespace, source=SOURCE,
        projects=pool_projects(pool), path=f'$.versions."{day}"')).scalars() if v), default='')
