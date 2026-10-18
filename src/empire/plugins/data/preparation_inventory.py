"""Bounded, read-only SQL inventory. Counts and date edges never prove completeness."""
import re
from datetime import datetime

from sqlalchemy import text

from empire.contracts.business_schema import DATASET_TABLE_GROUPS, TABLES
from empire.core.time import CHINA

DATE_COLUMNS = ('trade_date', 'report_date', 'event_date', 'source_date', 'listing_date',
                'unlock_date', 'announcement_date', 'published_at', 'suspended_at',
                'statistics_date', 'plan_date', 'unlock_month', 'effective_start')


def metadata(engine, contributions):
    owners = {}
    for c in contributions:
        for table in DATASET_TABLE_GROUPS.get(getattr(c, 'dataset', ''), ()):
            owners.setdefault(table, set()).add(c.requirement)
    with engine.connect() as conn:
        tables = conn.execute(text('SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH '
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' "
            'ORDER BY TABLE_NAME LIMIT 1001')).mappings().all()
        if len(tables) > 1000:
            raise ValueError('数据库超过1000张表，请缩小连接数据库范围')
        columns = conn.execute(text('SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION LIMIT 20001')).all()
        if len(columns) > 20000:
            raise ValueError('数据库字段超过盘点上限')
    by_table = {}
    for table, column in columns:
        by_table.setdefault(table, set()).add(column)
    rows = []
    for row in tables:
        name = row['TABLE_NAME']
        columns = by_table.get(name, set())
        rows.append(dict(table=name, requirements=sorted(owners.get(name, ())),
            category='配置 / 状态' if name in ('app_setting', 'collection_state') else
                     '研究业务' if name in owners else '目录外业务' if name in TABLES else '其他表',
            estimated_rows=int(row['TABLE_ROWS'] or 0), count=None, securities=None,
            bytes=int(row['DATA_LENGTH'] or 0) + int(row['INDEX_LENGTH'] or 0),
            date_column=next((c for c in DATE_COLUMNS if c in columns), ''),
            security_column='unified_code' if 'unified_code' in columns else
                            'index_code' if 'index_code' in columns else '',
            first=None, last=None, status='未精确盘点', checked_at=''))
    return rows


def count_table(engine, row):
    # Identifiers come only from current database metadata, and are still strictly bounded.
    if any(value and not re.fullmatch(r'[a-zA-Z0-9_]+', value)
           for value in (row['table'], row['date_column'], row['security_column'])):
        return {**row, 'status': '表或字段命名不在安全盘点范围'}
    projection = ['COUNT(*) AS total']
    # Very large detail tables use a covering count only. DISTINCT+MIN/MAX would
    # force an expensive full grouping scan without establishing any completeness.
    count_only = row.get('estimated_rows', 0) > 5_000_000
    if row['date_column'] and not count_only:
        projection += [f"MIN(`{row['date_column']}`) AS first_day", f"MAX(`{row['date_column']}`) AS last_day"]
    if row['security_column'] and not count_only:
        projection.append(f"COUNT(DISTINCT `{row['security_column']}`) AS securities")
    # MySQL kills a slow SELECT after 15s; a failed table remains unknown, never empty.
    with engine.connect() as conn:
        found = conn.execute(text('SELECT /*+ MAX_EXECUTION_TIME(15000) */ ' + ', '.join(projection)
                                  + f" FROM `{row['table']}`")).mappings().one()
    return {**row, 'count': int(found['total']), 'securities': found.get('securities'),
            'first': str(found['first_day']) if found.get('first_day') is not None else None,
            'last': str(found['last_day']) if found.get('last_day') is not None else None,
            'status': ('有数据；大明细表仅核实行数' if count_only else '有数据，完整性另查')
                      if found['total'] else '空表，不能推断来源无数据',
            'checked_at': datetime.now(CHINA).isoformat()}


async def inventory(context, contributions, exact=False, progress=None):
    mysql = context.optional('mysql.store')
    started = datetime.now(CHINA).isoformat()
    result = dict(rows=[], started_at=started, finished_at='', exact=exact, checking=exact,
                  checked=0, total=0, error='', note='行数与日期边界只说明库存，不证明集合完整；各表分时读取，非全库原子快照。')
    if mysql is None:
        result.update(error='MySQL 查询插件未运行', checking=False, finished_at=started)
        return result
    try:
        result['rows'] = await mysql.read(metadata, mysql.read_engine, contributions)
        result['total'] = len(result['rows'])
        if progress:
            progress(result)
        if exact:
            for index, row in enumerate(result['rows']):
                try:
                    result['rows'][index] = await mysql.read(count_table, mysql.read_engine, row)
                except Exception:
                    result['rows'][index] = {**row, 'status': '查询失败或超时，未确认'}
                result['checked'] += 1
                if progress:
                    progress(result)
    except Exception:
        result['error'] = '无法读取数据库库存；请检查连接及查询权限'
    finally:
        result.update(checking=False, finished_at=datetime.now(CHINA).isoformat())
    return result
