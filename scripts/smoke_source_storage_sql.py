"""Actual owned-MySQL SQL smoke with synthetic holders and no source requests."""
from __future__ import annotations

import argparse
import asyncio
import copy
import re
from collections import Counter
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

import source_verification as verification
from source_test_storage import initial_schema_statements
from source_verification import require
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.contracts.data import make_envelope
from empire.contracts.preparation_scope import PreparationScope
from empire.features.holders.contract import KINDS, digest, report_key, validate
from empire.plugins.infra.settings import SettingsStore


class SQLTrace:
    """Count successful statements only; never retain SQL values or parameters."""

    def __init__(self):
        self.counts = Counter()
        self.databases = set()
        self.lock = Lock()

    def capture(self, conn, cursor, statement, parameters, context, executemany):
        database = conn.engine.url.database or ''
        if not re.fullmatch(r'empire_verify_ths_[0-9a-f]{32}_test', database):
            return
        words = ' '.join(statement.upper().split())
        matched = re.match(r'(INSERT INTO|DELETE FROM|UPDATE)\s+`?([A-Z_]+)', words)
        label = (matched[1].lower() + ':' + matched[2].lower() if matched else
                 'show_create' if words.startswith('SHOW CREATE TABLE ') else
                 'show_tables' if words.startswith('SHOW FULL TABLES FROM ') else
                 words.split(' ', 1)[0].lower())
        with self.lock:
            self.databases.add(database)
            self.counts[label] += 1

    def snapshot(self):
        with self.lock:
            return dict(successful_statements=dict(sorted(self.counts.items())),
                        databases=sorted(self.databases))


def fixture_reports(security):
    """Small synthetic records, explicitly unrelated to actual issuer holdings."""
    result = {}
    for kind in KINDS:
        name = 'SQL冒烟合成债券' if kind == 'bond_holders' else security
        rows = []
        for day in ('2024-06-30', '2024-12-31'):
            member = dict(member_group='current', seq=1,
                source_rank=1 if kind == 'bond_holders' else None,
                holder_name='SQL冒烟合成持有人', holder_id=None, quantity='100',
                quantity_scale=1, quantity_decimals=0, ratio='1', change_quantity=None,
                change_label=None, actual_change=None, share_type=None,
                pledge_ratio=None, pledge_status=None)
            rows.append(dict(kind=kind, unified_code=security, instrument_key=digest(name),
                instrument_name=name, report_date=day, report_type='periodic',
                total_quantity='100', total_quantity_scale=1, total_quantity_decimals=0,
                total_ratio='1', ratio_basis='SQL冒烟合成口径', quality_flags=0,
                members=[member]))
        validate(kind, security, rows, today=datetime.now(UTC).date())
        result[kind] = rows
    return result


async def check_queries(manager, security, reports):
    comparisons = {}
    for kind in KINDS:
        query = manager.registry.get(kind + '.query')
        securities = await query.securities()
        require([row['unified_code'] for row in securities] == [security], '私有股票池不同')
        first = await query.browse(code=security, start='2024-01-01', end='2024-12-31', limit=1)
        require(len(first['rows']) == 1 and first['next'] is not None, '未覆盖正式游标分页')
        second = await query.browse(code=security, after=first['next'], limit=1)
        require(len(second['rows']) == 1 and second['next'] is None, '正式分页未正确结束')
        heads = first['rows'] + second['rows']
        require([row['report_key'] for row in heads] ==
                [report_key(row) for row in reversed(reports[kind])], '正式列表业务键集合或顺序不同')
        actual = [await query.detail(row['report_key']) for row in reversed(heads)]
        require(actual == reports[kind], '正式详情正文与合成输入不同')
        audit = await query.mysql.read(query.audit, PreparationScope())
        require(audit['complete'] and audit['securities'] == 1 and audit['missing'] == 0
                and audit['reports'] == 2 and audit['digests'] == {security: digest(reports[kind])},
                '正式 audit 未核实合成范围与内容')
        checks = await query.preparation_check()
        require(all(row.status == 'pass' for row in checks if row.criterion in
                    {'fields', 'keys', 'coverage', 'quality', 'freshness'}), '正式数据准备检查未通过')
        comparisons[kind] = dict(reports=2, keys=[report_key(row) for row in actual],
                                 content_sha256=digest(actual), audit_complete=True)
    return comparisons


async def smoke_scope(manager, selection, args, report, trace):
    report.update(mode='sql_positive_smoke', verification_scope='synthetic_owned_storage_sql',
                  source_requests=0, sample_30_applicable=False,
                  routing_policy={'not_applicable': 'No HTTP service or collector is started.'})
    result = report['results']['sql_smoke'] = dict(pipeline_verified=False, acceptance_complete=False,
                                                 synthetic=True, strict_proxy_verified=False)
    # Manager.start starts only these plugins and their declared dependencies.
    for plugin in ('pipeline.ingest', 'infra.download_settings', *(f'data.{kind}' for kind in KINDS)):
        await manager.start(plugin)
    mysql, redis = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
    ingest, archive = manager.registry.get('ingest.publish'), manager.registry.get('archive.worker')
    initial = trace.snapshot()
    require(initial['databases'] == [report['storage']['database']], 'SQL 观察出现非本轮私有库')
    require(initial['successful_statements'].get('create') == len(initial_schema_statements()),
            '实际 initialize_database 未执行全部现行精确 schema 语句')
    require(initial['successful_statements'].get('show_tables', 0) > 0 and
            initial['successful_statements'].get('show_create', 0) > 0,
            '真实 MySQL require_schema 未执行 metadata 检查')
    result['initialization_and_schema'] = initial
    settings = SettingsStore(mysql, redis.prefix)
    await settings.load('site')
    await settings.load('download')
    require((await manager.registry.get('download.settings').snapshot())['active'] is None,
            '冒烟意外启动 HTTP 下载资源')
    await settings.save('verifier_sql', 'smoke', {'revision': 1})
    before = trace.snapshot()['successful_statements']
    await settings.save('verifier_sql', 'smoke', {'revision': 1})
    after = trace.snapshot()['successful_statements']
    require(all(before.get(key, 0) == after.get(key, 0) for key in
                ('insert into:app_setting', 'update:app_setting')), '相同配置执行了 SQL 写入')
    await settings.save('verifier_sql', 'smoke', {'revision': 2})
    require((await settings.load('verifier_sql')) == {'smoke': {'revision': 2}}, '共享设置读写不同')
    result['shared_settings'] = dict(load=True, insert=True, unchanged_without_dml=True, update=True)
    security = selection['selected'][0]['unified_code']
    reports, batch = fixture_reports(security), uuid4().hex
    job = 'ths-holders-v1'

    async def publish(rows, page):
        state = await ingest.checkpoint(job)
        envelope = make_envelope(source='ths', dataset='holders.reports', schema_version=5,
            business_key=security, job_key=job, batch_id=batch, run_id=batch,
            payload=dict(page=page, unit=security, reports=rows, manifest=None, gaps=[]))
        await ingest.publish_page([envelope], job_key=job, expected_revision=state['revision'],
                                 cursor=dict(phase='sql_smoke', batch_id=batch, pages=page))
        await archive.flush()
        require(await redis.client.xlen(redis.stream) == 0 and not archive.blocked and
                not archive.blocked_projects and not archive.isolated, '合成消息未成功清队')

    await publish(reports, 1)
    result['initial_archive'] = await check_queries(manager, security, reports)
    # Exercise genuine replacement DELETE/INSERT and SQL state JSON updates.
    revised = copy.deepcopy(reports)
    for rows in revised.values():
        rows[0]['members'][0]['holder_name'] = 'SQL冒烟修订持有人'
    await publish(revised, 2)
    result['revised_archive'] = await check_queries(manager, security, revised)
    final_trace = trace.snapshot()
    require(final_trace['databases'] == [report['storage']['database']], 'SQL 观察出现非本轮私有库')
    counts = final_trace['successful_statements']
    for label in ('insert into:holder_report', 'insert into:holder_member', 'delete from:holder_member',
                  'insert into:collection_state', 'update:collection_state', 'update:app_setting'):
        require(counts.get(label, 0) > 0, '缺少真实 SQL 正向覆盖：' + label)
    active = [key for key, entry in manager.entries.items() if entry.context is not None]
    require(not any(key.startswith('collector.') or key in {'infra.http', 'collection.control'}
                    for key in active), '冒烟意外启动来源或调度插件')
    result.update(pipeline_verified=True, acceptance_complete=True, pending=0,
                  sql_trace=final_trace, active_plugins=active, source_requests=0)


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--pool-config', help='生产连接仅只读股票池、站点和下载设置')
    value.add_argument('--test-mysql-settings', required=True, help='显式13348独立MySQL JSON')
    value.add_argument('--output', required=True, help='build内未存在的报告文件')
    value.add_argument('--security', default='601139.SH', help='冻结股票池中的一只证券；仅合成记录')
    value.add_argument('--timeout', type=int, default=120)
    value.add_argument('--cleanup-only', action='store_true')
    value.add_argument('--run-state', help='原报告旁的.ownership.json')
    return value


async def main(options):
    if options.cleanup_only:
        return await verification.recover(options)
    options.random_count, options.seed, options.codes, options.proxy_only = 0, None, [options.security], False
    trace = SQLTrace()
    event.listen(Engine, 'after_cursor_execute', trace.capture)
    try:
        async def scope(manager, selection, args, report):
            await smoke_scope(manager, selection, args, report, trace)
        return await verification.verify(options, scope, subject='synthetic_sql_positive_smoke')
    finally:
        event.remove(Engine, 'after_cursor_execute', trace.capture)


if __name__ == '__main__':
    options = parser().parse_args()
    passed = asyncio.run(main(options))
    print(('CLEANUP COMPLETE' if options.cleanup_only else 'SQL SMOKE PASS') if passed else 'FAIL', flush=True)
    raise SystemExit(0 if passed else 1)
