"""Whole-list rights/issue observations using the shared owned verification lifecycle."""
import asyncio
import copy
import json
import sys

import source_verification as verification
from catalogue_verification import observe_fetch, observe_publish, require_drained
from dividend_capacity import compare_history
from foundation_verification import routed
from PySide6.QtCore import QCoreApplication
from source_verification import digest, require, strict_proxy
from sqlalchemy import text

from empire.core.config import default_config_path, load_config
from empire.features.capital_actions import issue_prefetch, lifecycle
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import KINDS, validate_rows
from empire.plugins.infra.mysql_store import make_engine


def reference(config, kind):
    table, project = KINDS[kind][1:]
    engine = make_engine(config['mysql'], pool_size=1)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            size = conn.execute(text(f'SELECT COUNT(*) AS count,COALESCE(SUM(OCTET_LENGTH(payload)),0) AS bytes '
                f'FROM {table}')).mappings().one()
            require(size['count'] <= 10000 and size['bytes'] <= 128 * 1024**2, '历史快照超过预算')
            rows = [dict(row) for row in conn.execute(text('SELECT *,RIGHT(unified_code,2) AS market,'
                f'LEFT(unified_code,6) AS code FROM {table} ORDER BY record_key LIMIT 10001')).mappings()]
            require(len(rows) == size['count'], '历史快照计数不同')
            for row in rows:
                if isinstance(row['payload'], str):
                    row['payload'] = json.loads(row['payload'])
            state = conn.execute(text('SELECT source,dataset,payload,updated_at FROM collection_state '
                'WHERE namespace=:ns AND project_id=:project'), dict(ns=config['redis']['namespace'],
                project=project)).mappings().first()
            state = dict(state) if state else None
            if state:
                require(state['source'] == 'tdx' and state['dataset'] == kind, '统一状态归属不符')
                if isinstance(state['payload'], str):
                    state['payload'] = json.loads(state['payload'])
                require(len(json.dumps(state['payload']).encode()) <= 16 * 1024**2, '统一状态超限')
            setting = conn.execute(text("SELECT payload FROM app_setting WHERE namespace=:ns "
                "AND kind='site' AND setting_key='tdx'"), dict(ns=config['redis']['namespace'])).scalar()
            if isinstance(setting, str):
                setting = json.loads(setting)
            server = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            conn.rollback()
    finally:
        engine.dispose()
    return dict(rows=rows, state=state, setting=setting, server_uuid=server)


def seed(mysql, namespace, kind, snapshot):
    table, project = KINDS[kind][1:]
    with mysql.engine.begin() as conn:
        for first in range(0, len(snapshot['rows']), 500):
            batch = [{**row, 'payload': json.dumps(row['payload'], ensure_ascii=False)}
                     for row in snapshot['rows'][first:first + 500]]
            conn.execute(text(f'INSERT INTO {table}(unified_code,record_key,name,event_date,payload,'
                'content_hash,version_observed_at) VALUES(:unified_code,:record_key,:name,:event_date,:payload,'
                ':content_hash,:version_observed_at)'), batch)
        if snapshot['state']:
            conn.execute(text('INSERT INTO collection_state(namespace,project_id,source,dataset,payload,updated_at) '
                'VALUES(:ns,:project,:source,:dataset,:payload,:updated_at)'), {**snapshot['state'],
                'ns': namespace, 'project': project, 'payload': json.dumps(snapshot['state']['payload'], ensure_ascii=False)})
        if snapshot['setting'] is not None:
            conn.execute(text("INSERT INTO app_setting(namespace,kind,setting_key,payload) VALUES(:ns,'site','tdx',:payload)"),
                         dict(ns=namespace, payload=json.dumps(snapshot['setting'], ensure_ascii=False)))


def without_detail(row):
    return {**row, 'data': {key: value for key, value in row['data'].items() if key != 'detail'}}


def check_details(rows, initial, downloaded):
    """Independent comparison of source details or unchanged, valid old details."""
    from empire.features.capital_actions.issue_contract import validate
    old = {r['record_key']: r for r in initial}
    for row in rows:
        detail = row['data']['detail']
        ident = row['data']['source_id']
        if ident in downloaded:
            wanted = copy.deepcopy(downloaded[ident])
            if wanted.get('availability') == 'unavailable':
                prior = old.get(row['record_key'], {}).get('data', {}).get('detail')
                if prior:
                    last = prior.get('last_available') if prior.get('availability') == 'unavailable' else prior
                    if last:
                        wanted['last_available'] = last
            require(detail == wanted, '正式详情与本轮来源不同')
        else:
            candidates = [r for r in initial if r['data']['source_id'] == ident
                          and without_detail(r)['data'] == without_detail(row)['data']]
            require(bool(candidates) and all(validate(r['data']['detail']) == detail for r in candidates),
                    '未请求详情与可复用的旧来源证明不同')


async def scope(manager, args, report, snapshot):
    kind = args.kind
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    await mysql.control(seed, mysql, store.prefix, kind, snapshot)
    await manager.start('collector.tdx_' + kind)
    collector, query = manager.registry.get('collector.tdx_' + kind), manager.registry.get(kind + '.query')
    source_rows, current, details, published, counts = [], [], {}, [], {}
    result = report['results'][kind] = dict(pipeline_verified=False, acceptance_complete=False,
        routes=counts, published=published, scope='whole current source list; incremental issue details')
    original, fetch_detail, publish = lifecycle.complete_response, issue_prefetch.fetch_detail, collector.ingest.publish_page

    def remember(arguments, value):
        require(not source_rows and arguments[1] == kind, '完整列表重复或栏目改变')
        source_rows.extend(copy.deepcopy(value[0]))

    def remember_detail(arguments, value):
        ident = arguments[1]['data']['source_id']
        require(ident not in details, '同编号详情重复消费')
        details[ident] = value

    def check(envelope):
        require(envelope.dataset == kind + '.unit' and envelope.job_key == collector.job_key, '入队归属改变')
        payload = envelope.raw_payload
        if payload['unit'] != 'manifest':
            validate_rows(kind, payload['unit'], payload['rows'])
            current.extend(copy.deepcopy(payload['rows']))

    lifecycle.complete_response = observe_fetch(original, remember)
    issue_prefetch.fetch_detail = observe_fetch(fetch_detail, remember_detail)
    collector.ingest.publish_page = observe_publish(publish, check, published)
    try:
        result['outcome'] = await routed(lambda: collector.execute(fresh=False, baseline_revision=0), counts, args.proxy_only)
    finally:
        lifecycle.complete_response, issue_prefetch.fetch_detail = original, fetch_detail
        collector.ingest.publish_page = publish
        result['stats'] = dict(collector.stats)
    expected = {r['record_key']: r for r in source_rows}
    actual_source = {r['record_key']: without_detail(r) for r in current}
    require(len(expected) == len(source_rows) and len(actual_source) == len(current), '列表或入队业务键重复')
    require(expected == actual_source, '完整列表与入队集合内容不符')
    initial = [decode(r) for r in snapshot['rows']]
    if kind == 'additional_issues':
        check_details(current, initial, details)
    rows = []
    while True:
        page = await query.list_events(limit=500, offset=len(rows))
        rows.extend(page)
        require(len(rows) <= 10000, '正式查询超限')
        if len(page) < 500:
            break
    result['comparison'] = compare_history(initial, current, rows)
    result['source_count'], result['source_digest'] = len(source_rows), digest(source_rows)
    result['details'] = {key: digest(value) for key, value in details.items()}
    result['pending'] = await require_drained(manager)
    result['preparation'] = [dict(criterion=c.criterion, status=c.status, measured=c.measured)
                             for c in await query.preparation_check()]
    result.update(pipeline_verified=True, acceptance_complete=True, strict_proxy_verified=strict_proxy(counts, 1))


async def verify(args):
    snapshot = None
    def prepare(selection, options, report):
        nonlocal snapshot
        snapshot = reference(load_config(options.pool_config or default_config_path()), options.kind)
        require(snapshot['server_uuid'] == report['source_server_uuid'], '快照实际生产实例发生变化')
        report['reference'] = dict(server_uuid=snapshot['server_uuid'], rows=len(snapshot['rows']),
            content_digest=digest([decode(r) for r in snapshot['rows']]), setting_digest=digest(snapshot['setting']))
    async def run(manager, selection, options, report):
        await scope(manager, options, report, snapshot)
    return await verification.verify(args, run, subject='capital_actions', prepare_scope=prepare,
        non_stock_scope=dict(unit='complete source list', fixed=[],
        reason='配股/增发按全栏目完整响应，不以当前股票池过滤；纯组织迁移，不声明随机30股票准入'))


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=3600)
    parser.add_argument('--kind', choices=('rights_issues', 'additional_issues'), required=True)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args))
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
