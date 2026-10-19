"""Deterministic synthetic rows in a verified, UUID-owned local MySQL schema."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def fixtures(protocol):
    spec = protocol['fixture']
    stamp = datetime.fromisoformat(spec['fixed_datetime'])
    news, reports, heads, members = [], [], [], []
    for index in range(1, spec['news_rows'] + 1):
        moment = stamp + timedelta(seconds=index // 2)
        news.append(dict(source='sina', news_id=index,
                         title=f'固定新闻 {index:05d} ' + ('产业' if index % 3 == 0 else '市场'),
                         content=('固定合成新闻正文；仅用于离线性能回归。' * 100)
                         [:spec['news_content_characters']],
                         published_at=moment, source_updated_at=moment,
                         is_important=index % 10 == 0, tags='[{"id":"1","name":"基准"}]',
                         url='https://example.invalid/news', first_seen_at=stamp,
                         version_observed_at=stamp))
    for kind in spec['holder_kinds']:
        for security in range(spec['holder_securities']):
            symbol = f'{600000 + security:06d}.SH'
            for period in range(spec['holder_periods']):
                quarter = period + 2
                year, month = 2023 + quarter // 4, (quarter % 4 + 1) * 3
                day = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
                names = []
                for group, count in (('current', spec['holder_current_members']),
                                     ('exited', spec['holder_exited_members'])):
                    for seq in range(1, count + 1):
                        names.append(dict(member_group=group, seq=seq,
                            source_rank=seq if kind == 'bond_holders' else None,
                            holder_name=f'固定持有人 {group} {seq:02d}', holder_id=None,
                            quantity='100' if group == 'current' else '20', quantity_scale=1,
                            quantity_decimals=0, ratio='1', change_quantity='0',
                            change_label='unchanged' if group == 'current' else 'exited',
                            actual_change=None, share_type='普通',
                            pledge_ratio=None, pledge_status=None))
                instrument = '固定合成债券' if kind == 'bond_holders' else symbol
                row = dict(kind=kind, unified_code=symbol,
                           instrument_key=digest(instrument), instrument_name=instrument,
                           report_date=day, report_type='periodic',
                           total_quantity=str(100 * spec['holder_current_members']),
                           total_quantity_scale=1, total_quantity_decimals=0,
                           total_ratio=str(spec['holder_current_members']), ratio_basis='total',
                           quality_flags=0, members=names)
                key = digest([row[k] for k in
                              ('kind', 'unified_code', 'instrument_key', 'report_date', 'report_type')])
                heads.append({k: v for k, v in row.items() if k != 'members'} | dict(
                    report_key=key, member_count=spec['holder_current_members'],
                    exit_count=spec['holder_exited_members'], content_hash=digest(row),
                    version_observed_at=stamp))
                members.extend(dict(member, report_key=key) for member in names)
                reports.append((key, row))
    return dict(news=news, heads=heads, members=members, reports=reports)


def table_definitions(root, protocol):
    sql = (root / 'sql/schema.sql').read_text('utf-8')
    result = {}
    for table in protocol['mysql']['tables']:
        if not re.fullmatch('[a-z_]+', table):
            raise ValueError('Invalid benchmark table')
        match = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)
        if not match:
            raise ValueError('Missing production table DDL: ' + table)
        result[table] = match[0]
    return result


def validate_settings(root, settings, protocol):
    expected = protocol['mysql']
    if (settings.get('host') != expected['host'] or settings.get('host') != '127.0.0.1'
            or type(settings.get('port')) is not int or settings['port'] != expected['port']
            or settings['port'] in {3306, 3307}):
        raise ValueError('Benchmark requires the explicitly registered isolated loopback MySQL')
    datadir = (root / expected['datadir_relative']).resolve()
    if not datadir.is_relative_to((root / 'build').resolve()):
        raise ValueError('Benchmark MySQL datadir must be inside this workspace build directory')
    return datadir


@contextmanager
def private_database(root, settings, protocol):
    from sqlalchemy import event, text

    from empire.plugins.infra.mysql_store import make_engine

    datadir = validate_settings(root, settings, protocol)
    admin = make_engine(dict(settings, database='mysql'), pool_size=1)
    database = 'empire_archbench_' + uuid4().hex + '_test'
    engine, created = None, False
    state = dict(cleaned=False)
    try:
        with admin.connect() as conn:
            environment = dict(conn.execute(text('SELECT @@version AS version,@@port AS port,'
                '@@datadir AS datadir,@@innodb_buffer_pool_size AS buffer_pool_bytes,'
                '@@innodb_flush_log_at_trx_commit AS flush_at_commit')).mappings().one())
            if (Path(environment.pop('datadir')).resolve() != datadir
                    or environment['port'] != protocol['mysql']['port']
                    or environment['flush_at_commit'] != protocol['mysql']['innodb_flush_log_at_trx_commit']):
                raise ValueError('Isolated MySQL process identity/settings differ from frozen protocol')
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        engine = make_engine(dict(settings, database=database), pool_size=2)
        readonly = False

        def guard(conn, cursor, statement, parameters, context, executemany):
            if conn.engine.url.database != database or re.search(
                    r'\b(?:USE|CREATE\s+DATABASE|DROP\s+DATABASE)\b', statement, re.I):
                raise RuntimeError('Benchmark SQL escaped its owned schema')
            if readonly and (not statement.lstrip().upper().startswith('SELECT ')
                             or re.search(r'\bFOR\s+UPDATE\b', statement, re.I)):
                raise RuntimeError('Formal query attempted a non-read statement')
            if re.search(r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+`?\w+`?\s*\.', statement, re.I):
                raise RuntimeError('Cross-schema SQL is forbidden in this benchmark')

        event.listen(engine, 'before_cursor_execute', guard)
        rows = fixtures(protocol)
        ddl = table_definitions(root, protocol)
        with engine.begin() as conn:
            for statement in ddl.values():
                conn.exec_driver_sql(statement)
            for table, values in (('finance_news', rows['news']), ('holder_report', rows['heads']),
                                  ('holder_member', rows['members'])):
                fields = list(values[0])
                query = text(f'INSERT INTO {table} (' + ','.join(fields) + ') VALUES ('
                             + ','.join(':' + key for key in fields) + ')')
                conn.execute(query, values)
                if conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one() != len(values):
                    raise RuntimeError('Synthetic fixture row count differs')
        readonly = True
        state.update(mysql=environment, schema=database, fixture_sha256=digest(rows),
                     ddl_sha256=digest(ddl))
        yield engine, rows, state
    finally:
        if engine:
            engine.dispose()
        try:
            if created:
                if not re.fullmatch(r'empire_archbench_[a-f0-9]{32}_test', database):
                    raise RuntimeError('Refusing cleanup of an unowned schema')
                with admin.connect() as conn:
                    conn.exec_driver_sql(f'DROP DATABASE `{database}`')
            state['cleaned'] = True
        finally:
            admin.dispose()
