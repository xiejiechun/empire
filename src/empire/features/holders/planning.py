"""Bounded per-security maintenance from existing confirmed state, not a gap frontier."""
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from empire.contracts.collector import NEXT_MAINTENANCE_DUE
from empire.core.time import CHINA
from empire.features.holders.contract import KINDS, digest
from empire.plugins.pipeline.fingerprints import FingerprintCache


def due_at(stamp):
    schedule = NEXT_MAINTENANCE_DUE.get()
    value = schedule(stamp.timestamp()) if schedule else None
    return datetime.fromtimestamp(value, UTC) if value is not None else stamp + timedelta(days=1)


def read_units(conn, namespace):
    # Project only scheduling fields; never transfer historical report bodies
    # or the multi-megabyte project payload into a maintenance planner.
    fields = ('observed_at', 'contract', 'count', 'digest', 'fingerprint_hash')
    projection = ','.join("'" + key + "',JSON_EXTRACT(p.unit,'$." + key + "')" for key in fields)
    projection += ", 'gap_count',JSON_LENGTH(JSON_EXTRACT(p.unit,'$.source_gaps'))"
    query = """SELECT p.unified_code,JSON_OBJECT(""" + projection + """) AS summary
        FROM (SELECT s.unified_code,JSON_EXTRACT(c.payload,CONCAT('$.units."',s.unified_code,'"')) AS unit
              FROM stock s LEFT JOIN collection_state c
                ON c.namespace=:namespace AND c.project_id='ths-holders' AND c.source='ths'
                AND JSON_EXTRACT(c.payload,'$.contract_version')=4
              ORDER BY s.unified_code LIMIT 15001) p"""
    rows = conn.execute(text(query), {'namespace': namespace}).mappings().all()
    if len(rows) > 15000:
        raise ValueError('持有人维护范围超限')
    result = {}
    for row in rows:
        value = row['summary']
        value = json.loads(value) if isinstance(value, str) else value
        if (value.get('contract') == 4 and type(value.get('count')) is int and 0 <= value['count'] <= 300
                and type(value.get('gap_count')) is int and 0 <= value['gap_count'] <= 100
                and isinstance(value.get('digest'), str) and re.fullmatch('[a-f0-9]{64}', value['digest'])):
            result[row['unified_code']] = value
    return result


async def confirmed_units(query, now):
    def read():
        with query.mysql.read_engine.connect() as conn:
            return read_units(conn, query.namespace)
    units = await query.mysql.read(read)
    version = query.mapping.FINGERPRINT_VERSION
    valid = {}
    for key, value in units.items():
        try:
            stamp = version.key([value['observed_at']], now=now)[0]
            if stamp <= now:
                valid[key] = {**value, 'stamp': stamp}
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    store = query.context.optional('redis.store') if query.context else None
    if store:
        cache = FingerprintCache(store, query.archive_settings, lambda _: version)
        keys = [key for key, value in valid.items() if value.get('fingerprint_hash')]
        try:
            for offset in range(0, len(keys), 200):
                cached = await cache.peek(query.mapping.FINGERPRINT_NAMESPACE, 'ths', keys[offset:offset + 200])
                for key, value in cached.items():
                    stamp = version.key(value['version'], now=now)[0]
                    if value['hash'] == valid[key]['fingerprint_hash'] and valid[key]['stamp'] <= stamp <= now:
                        valid[key]['stamp'] = stamp
        except Exception:
            pass  # Cache is optional; already confirmed SQL dates remain usable.
    return valid


def choose(stocks, units, now, *, fresh=False, started=None):
    return [stock for stock in stocks if fresh or stock['unified_code'] not in units
            or (units[stock['unified_code']]['stamp'] < started if started is not None
                else due_at(units[stock['unified_code']]['stamp']) <= now)]


def manifest_for(keys, summaries):
    rolling, count = digest([]), 0
    kinds = {kind: dict(count=0, digest=digest([])) for kind in KINDS}
    for key in keys:
        row = summaries[key]
        count += row['count']
        rolling = digest([rolling, key, row['digest'], row['count']])
        for kind, part in row['kinds'].items():
            kinds[kind]['count'] += part['count']
            kinds[kind]['digest'] = digest([kinds[kind]['digest'], key, part['digest'], part['count']])
    return dict(units=len(keys), count=count, scope_hash=digest(keys), digest=rolling,
                securities=keys, kinds=kinds)


def gap_notice(units, checked):
    gaps = {key: value for key, value in units.items() if value['gap_count']}
    if not gaps:
        return '', 0, 0
    next_check = min(due_at(row['stamp']) for row in gaps.values()).astimezone(CHINA)
    count = sum(row['gap_count'] for row in gaps.values())
    notice = (f'本轮检查{checked}只证券，可识别报告已确认归档；{len(gaps)}只证券共{count}份债券报告'
              '名称为空，属于持续来源缺陷：' + '、'.join(sorted(gaps)[:5]) + ('等' if len(gaps) > 5 else '')
              + f'。等待来源补齐；预计{next_check:%Y-%m-%d %H:%M}起随这些证券的正常更新复查，'
              '以实际任务执行为准。同周期无需反复点击继续采集；仅对应债券报告仍有缺口，其他有效数据正常更新。')
    return notice, len(gaps), count
