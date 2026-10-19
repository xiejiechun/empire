"""Canonical, streaming inventories shared by the explicit v1->v2 maintenance tool."""
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import inspect, text

from empire.contracts.business_schema import FIXED_SOURCES
from empire.features.kaipanla.storage_contract import MARKET_TABLES

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TABLES = set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)',
    (ROOT / 'sql/legacy/business-v1.sql').read_text('utf-8')))
LEGACY_SOURCES = {**{t: s for t, s in FIXED_SOURCES.items()
                    if t not in MARKET_TABLES and t in LEGACY_TABLES}, 'stock_intraday': 'kaipanla'}
OLD = tuple(LEGACY_SOURCES) + ('finance_news', 'collection_state', 'app_setting')
NEW = OLD + ('suspension_source_date',)
PREFIX = 'empire_v2_'
BACKUP = 'empire_v1_'


def definitions():
    body = (ROOT / 'sql/schema.sql').read_text(encoding='utf-8')
    body += '\n' + (ROOT / 'sql/legacy/intraday-v2.sql').read_text(encoding='utf-8')
    return {
        m.group(1): m.group(0) for m in re.finditer(
            r'CREATE TABLE IF NOT EXISTS (\w+) \(.*?\) ENGINE=.*?;', body, re.S)}


def quote(name):
    if name not in NEW and not any(name == p + t for p in (PREFIX, BACKUP) for t in NEW):
        raise ValueError('非维护白名单表')
    return '`' + name + '`'


def target_columns(table):
    return re.findall(r'^    (\w+) (?:VARCHAR|CHAR|DATE|BOOLEAN|JSON|BIGINT|MEDIUMTEXT)',
                      definitions()[table], re.M)


def target_keys(table):
    return [v.strip() for v in re.search(r'PRIMARY KEY \(([^)]+)\)', definitions()[table])[1].split(',')]


def expression(table, column, *, old):
    if not old:
        return '`' + column + '`'
    if column == 'unified_code' and table != 'stock':
        return "CONCAT(code,'.',market)"
    if column == 'source_dates_known':
        return '(source_dates IS NOT NULL AND JSON_LENGTH(source_dates)>0)'
    return '`' + column + '`'


def selection(table, prefix='', *, old=False):
    if table == 'suspension_source_date' and old:
        parent = quote(prefix + 'suspension_event')
        return ("SELECT d.source_date,CONCAT(s.code,'.',s.market) AS unified_code,"
                's.suspended_at,s.resume_key,s.record_key FROM ' + parent +
                " s JOIN JSON_TABLE(s.source_dates,'$[*]' COLUMNS(source_date DATE PATH '$' ERROR ON ERROR)) d")
    columns = [expression(table, col, old=old) + ' AS `' + col + '`' for col in target_columns(table)]
    return 'SELECT ' + ','.join(columns) + ' FROM ' + quote(prefix + table)


def inventory(engine, prefix='', *, old=False):
    results = {}
    with engine.connect().execution_options(stream_results=True, yield_per=128) as conn:
        conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        for table in NEW:
            digest, count = hashlib.sha256(), 0
            statement = selection(table, prefix, old=old)
            statement += ' ORDER BY ' + ','.join('`' + k + '`' for k in target_keys(table))
            rows = conn.execute(text(statement)).mappings()
            try:
                for row in rows:
                    value = dict(row)
                    for key in ('payload', 'tags'):
                        if key in value and isinstance(value[key], str):
                            value[key] = json.loads(value[key])
                    wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()
                    digest.update(len(wire).to_bytes(8, 'big'))
                    digest.update(wire)
                    count += 1
            finally:
                rows.close()
            results[table] = dict(rows=count, sha256=digest.hexdigest())
        conn.rollback()
    return results


def validate_old(engine):
    with engine.connect() as conn:
        stock_count = conn.execute(text('SELECT COUNT(*) FROM stock')).scalar_one()
        publications = conn.execute(text("SELECT JSON_EXTRACT(payload,'$.publication.row_count') "
            "FROM collection_state WHERE project_id='sina-stocks' AND source='sina'")).scalars()
        for count in publications:
            if count is None or int(count) != stock_count:
                raise ValueError('股票业务数量与已发布状态不一致，先修复数据再迁移')
        for table, source in LEGACY_SOURCES.items():
            columns = {c['name'] for c in inspect(conn).get_columns(table)}
            if 'source' not in columns:
                raise ValueError(f'{table} 不是待迁移旧结构')
            extra = conn.execute(text(f'SELECT DISTINCT source FROM {quote(table)} WHERE source<>:source'),
                                 dict(source=source)).scalars().all()
            if extra:
                raise ValueError(f'{table} 存在额外来源，拒绝迁移')
            if 'market' in columns:
                invalid = conn.execute(text(f'SELECT 1 FROM {quote(table)} WHERE '
                    "market NOT IN ('SH','SZ','BJ') OR code NOT REGEXP '^[0-9]{6}$' LIMIT 1")).first()
                if invalid:
                    raise ValueError(f'{table} 证券身份无效')
        if conn.execute(text("SELECT 1 FROM stock WHERE unified_code<>CONCAT(code,'.',market) "
            "OR source_symbol<>CONCAT(LOWER(market),code) OR node<>'hs_a' LIMIT 1")).first():
            raise ValueError('股票来源符号/node/证券身份不能无损推导')
        if conn.execute(text("SELECT 1 FROM suspension_event WHERE source_dates IS NOT NULL AND "
            "JSON_TYPE(source_dates)<>'ARRAY' LIMIT 1")).first():
            raise ValueError('停复牌来源日期不是数组')
        # Reject duplicates and noncanonical dates; never silently DISTINCT source evidence.
        rows = conn.execution_options(stream_results=True).execute(text(
            'SELECT source_dates FROM suspension_event')).scalars()
        try:
            from datetime import date
            for raw in rows:
                days = json.loads(raw) if isinstance(raw, str) else raw
                if days is not None and (not isinstance(days, list) or
                    any(not isinstance(d, str) or date.fromisoformat(d).isoformat() != d for d in days) or
                    days != sorted(set(days))):
                    raise ValueError('停复牌来源日期重复、乱序或格式错误')
        finally:
            rows.close()
