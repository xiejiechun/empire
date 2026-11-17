"""Confirmed security summaries for THS whole-response maintenance planning."""
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.collector import NEXT_MAINTENANCE_DUE
from empire.plugins.pipeline.fingerprints import FingerprintCache


def due(stamp, now):
    schedule = NEXT_MAINTENANCE_DUE.get()
    value = schedule(stamp.timestamp()) if schedule else None
    return (datetime.fromtimestamp(value, UTC) if value is not None else stamp + timedelta(days=1)) <= now


async def confirmed_units(query, project, mapping, *, financial=False):
    # SQL projects only bounded scheduling summaries, never historical bodies.
    key = "CONCAT(RIGHT(s.unified_code,2),':',LEFT(s.unified_code,6))" if financial else 's.unified_code'
    count = "JSON_LENGTH(JSON_EXTRACT(p.unit,'$.dates'))" if financial else "JSON_EXTRACT(p.unit,'$.count')"
    checksum = 'digest' if financial else 'content_digest'
    sql = """SELECT p.identity,JSON_OBJECT(
        'observed_at',JSON_EXTRACT(p.unit,'$.observed_at'),
        'digest',JSON_EXTRACT(p.unit,'$.""" + checksum + """'),
        'fingerprint_hash',JSON_EXTRACT(p.unit,'$.fingerprint_hash'),
        'count',""" + count + """) AS summary
        FROM (SELECT """ + key + """ AS identity,
          JSON_EXTRACT(c.payload,CONCAT('$.units."',""" + key + """,'"')) AS unit
          FROM stock s LEFT JOIN collection_state c ON c.namespace=:namespace
            AND c.project_id=:project AND c.source='ths'
            AND JSON_EXTRACT(c.payload,'$.contract_version')=1
          ORDER BY s.unified_code LIMIT 15001) p"""

    def read():
        with query.mysql.read_engine.connect() as conn:
            return conn.execute(text(sql), dict(namespace=query.namespace, project=project)).mappings().all()
    rows = await query.mysql.read(read)
    if len(rows) > 15000:
        raise ValueError('同花顺证券维护范围超限')
    now, valid = datetime.now(UTC), {}
    for row in rows:
        value = row['summary']
        value = json.loads(value) if isinstance(value, str) else value
        try:
            stamp = mapping.FINGERPRINT_VERSION.key([value['observed_at']], now=now)[0]
            if (stamp <= now and type(value['count']) is int and 0 <= value['count'] <= 100000
                    and isinstance(value['digest'], str) and re.fullmatch('[a-f0-9]{64}', value['digest'])):
                valid[row['identity']] = {**value, 'stamp': stamp}
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    store = query.context.optional('redis.store') if query.context else None
    if store:
        cache = FingerprintCache(store, query.archive_settings, lambda _: mapping.FINGERPRINT_VERSION)
        keys = [k for k, v in valid.items() if v.get('fingerprint_hash')]
        try:
            for offset in range(0, len(keys), 200):
                values = await cache.peek(mapping.FINGERPRINT_NAMESPACE, 'ths', keys[offset:offset + 200])
                for key, value in values.items():
                    stamp = mapping.FINGERPRINT_VERSION.key(value['version'], now=now)[0]
                    if value['hash'] == valid[key]['fingerprint_hash'] and valid[key]['stamp'] <= stamp <= now:
                        valid[key]['stamp'] = stamp
        except Exception:
            pass  # Optional cache; SQL confirmation remains authoritative.
    return valid
