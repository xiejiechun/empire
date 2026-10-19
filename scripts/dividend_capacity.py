"""Observe the formal dividend pipeline in owned storage; preserve historical rows."""
import copy
import json
from datetime import UTC, datetime
from time import perf_counter

from catalogue_verification import observe_fetch, observe_publish, require_drained
from foundation_verification import routed
from source_verification import digest, require, strict_proxy
from sqlalchemy import text

from empire.features.capital_actions import dividend_history, source
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import unit_key
from empire.plugins.infra.mysql_store import make_engine

LIMITS = dict(source_rows=100000, planned_periods=1000, payload_bytes=134217728,
              maximum_payload_bytes=65536, query_p95_upper_ms=1500)
PAYLOAD_SIZE = 'OCTET_LENGTH(CAST(payload AS CHAR CHARACTER SET utf8mb4))'


def json_rows(rows):
    return [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()} for row in rows]


def read_snapshot(config):
    """All production reads use one consistent, READ ONLY transaction, then close."""
    engine = make_engine(config['mysql'], pool_size=1)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            server = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            stocks = [dict(row) for row in conn.execute(text(
                'SELECT unified_code,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings()]
            require(0 < len(stocks) <= 15000 and len({r['unified_code'] for r in stocks}) == len(stocks),
                    '股票池为空、重复或超限')
            settings = [dict(row) for row in conn.execute(text(
                "SELECT kind,setting_key,payload FROM app_setting WHERE namespace=:ns AND "
                "((kind='site' AND setting_key='tdx') OR (kind='download' AND setting_key='global'))"),
                dict(ns=config['redis']['namespace'])).mappings()]
            for row in settings:
                if isinstance(row['payload'], str):
                    row['payload'] = json.loads(row['payload'])
            size = conn.execute(text(f'SELECT COUNT(*) AS count,COALESCE(SUM({PAYLOAD_SIZE}),0) AS bytes '
                'FROM dividend_plan')).mappings().one()
            require(size['count'] <= LIMITS['source_rows'] and size['bytes'] <= LIMITS['payload_bytes'],
                    '已有分红超出有界快照预算；不读取全表')
            rows = [dict(row) for row in conn.execute(text('SELECT *,RIGHT(unified_code,2) AS market,'
                'LEFT(unified_code,6) AS code FROM dividend_plan ORDER BY record_key LIMIT 100001')).mappings()]
            state = conn.execute(text('SELECT source,dataset,payload,updated_at FROM collection_state '
                'WHERE namespace=:ns AND project_id=:project'), dict(ns=config['redis']['namespace'],
                project='tdx-dividends')).mappings().first()
            state = dict(state) if state else None
            require(len(rows) == size['count'], '快照计数不同')
            for row in rows:
                if isinstance(row['payload'], str):
                    row['payload'] = json.loads(row['payload'])
            if state:
                require(state['source'] == 'tdx' and state['dataset'] == 'dividends', '统一状态归属错误')
                if isinstance(state['payload'], str):
                    state['payload'] = json.loads(state['payload'])
                require(len(json.dumps(state['payload']).encode()) <= 16 * 1024**2, '分红状态快照超限')
            conn.rollback()
    finally:
        engine.dispose()
    canonical = [decode(row) for row in rows]
    identity = dict(read_at=datetime.now(UTC).isoformat(), server_uuid=server, stocks=len(stocks),
                    pool_digest=digest(stocks), settings_digest=digest(settings),
                    existing_rows=len(rows), existing_digest=digest(canonical),
                    state_digest=digest(json_rows([state])) if state else digest(None))
    return dict(server_uuid=server, stocks=stocks, settings=settings, rows=rows, state=state, identity=identity)


def seed_history(storage, snapshot):
    engine = make_engine(storage.settings, pool_size=1)
    try:
        with engine.begin() as conn:
            for first in range(0, len(snapshot['rows']), 500):
                batch = [{**row, 'payload': json.dumps(row['payload'], ensure_ascii=False)}
                         for row in snapshot['rows'][first:first + 500]]
                conn.execute(text('INSERT INTO dividend_plan(unified_code,record_key,name,event_date,payload,'
                    'content_hash,version_observed_at) VALUES(:unified_code,:record_key,:name,:event_date,:payload,'
                    ':content_hash,:version_observed_at)'), batch)
            state = snapshot['state']
            if state:
                conn.execute(text('INSERT INTO collection_state(namespace,project_id,source,dataset,payload,'
                    'updated_at) VALUES(:ns,:project,:source,:dataset,:payload,:updated_at)'),
                    {**state, 'ns': storage.namespace, 'project': 'tdx-dividends',
                     'payload': json.dumps(state['payload'], ensure_ascii=False)})
    finally:
        engine.dispose()


def compare_history(existing, current, actual):
    def index(rows):
        result = {row['record_key']: row for row in rows}
        require(len(result) == len(rows), '业务键重复，不能用覆盖隐藏')
        return result
    old, new, stored = index(existing), index(current), index(actual)
    require(stored == old | new, '正式查询与保留历史加本轮来源的集合或内容不同')
    missing = sorted(old.keys() - new.keys())
    return dict(existing=len(old), current=len(new), stored=len(stored),
                retained_history_count=len(missing), retained_history_keys=missing,
                retained_history_digest=digest([old[key] for key in missing]),
                current_digest=digest([new[key] for key in sorted(new)]),
                stored_digest=digest([stored[key] for key in sorted(stored)]))


def capacity_checks(measured):
    require(set(LIMITS) <= measured.keys(), '缺少完整容量指标')
    require(all(isinstance(measured[k], (int, float)) and not isinstance(measured[k], bool)
                and 0 <= measured[k] <= maximum for k, maximum in LIMITS.items()), '容量超过原冻结阈值')
    require(measured['planned_periods'] > 0, '无真实报告期')
    return True


async def verify_scope(manager, snapshot, args, report):
    await manager.start('collector.tdx_dividends')
    collector = manager.registry.get('collector.tdx_dividends')
    query = manager.registry.get('dividends.query')
    periods, source_periods, sources, published, counts = [], {}, {}, [], {}
    result = report['results']['dividends'] = dict(pipeline_verified=False, acceptance_complete=False,
        routes=counts, source_periods=source_periods, source_units=sources, published=published,
        limits=LIMITS, protocol='architecture-e5-capacity-protocol-2026-10-20', sample_30_claimed=False)
    original_plan, original_fetch = dividend_history.report_periods, source.complete_response
    original_history, original_publish = dividend_history.collect_history, collector.ingest.publish_page

    async def plan(*a, **kw):
        values = await original_plan(*a, **kw)
        require(not periods and values == sorted(set(values)), '报告期计划重复或无序')
        periods.extend(values)
        result['planned_dates'] = values
        return values

    def remember(arguments, value):
        require(arguments[1] == 'dividends' and len(arguments) == 3, '来源调用范围改变')
        period = arguments[2]
        require(period in periods and period not in source_periods, '来源报告期未知或重复消费')
        rows, _ = value
        source_periods[period] = dict(count=len(rows), digest=digest(rows))

    current = []

    async def history(*a, **kw):
        units, observed, checksum = await original_history(*a, **kw)
        for unit, rows in units.items():
            current.extend(copy.deepcopy(rows))
            sources[unit] = dict(count=len(rows), digest=digest(rows))
        return units, observed, checksum

    def check(envelope):
        payload = envelope.raw_payload
        require(envelope.dataset == 'dividends.unit' and envelope.job_key == collector.job_key,
                '发布归属错误')
        if payload['unit'] != 'manifest':
            require(sources[payload['unit']] == dict(count=len(payload['rows']), digest=digest(payload['rows'])),
                    '来源与入队集合或内容不同')

    dividend_history.report_periods = plan
    source.complete_response = observe_fetch(original_fetch, remember)
    dividend_history.collect_history = history
    collector.ingest.publish_page = observe_publish(original_publish, check, published)
    try:
        result['outcome'] = await routed(lambda: collector.execute(fresh=False, baseline_revision=0),
                                         counts, args.proxy_only)
    finally:
        dividend_history.report_periods, source.complete_response = original_plan, original_fetch
        dividend_history.collect_history, collector.ingest.publish_page = original_history, original_publish
    require(set(periods) == set(source_periods), '本轮报告期未全部完成')
    require(set(sources) == {unit_key(row) for row in await query.securities()}, '本轮证券池未全部处理')
    require({r['identity'] for r in published} == set(sources) | {'manifest'}
            and len(published) == len(sources) + 1, '入队单元缺漏或重复')
    actual = []
    while True:
        page = await query.list_events(limit=500, offset=len(actual))
        actual.extend(page)
        require(len(actual) <= 100000, '正式查询超出容量预算')
        if len(page) < 500:
            break
    result['comparison'] = compare_history([decode(r) for r in snapshot['rows']], current, actual)
    result['pending'] = await require_drained(manager)
    result['preparation'] = [dict(criterion=c.criterion, status=c.status, measured=c.measured) for c in await query.preparation_check()]
    timings, baseline = [], None
    for _ in range(10):
        start = perf_counter()
        rows = await query.list_events(code='600007', limit=51)
        timings.append((perf_counter() - start) * 1000)
        checksum = digest(rows)
        require(baseline is None or baseline == checksum, '重复正式查询内容改变')
        baseline = checksum
    def size():
        with query.mysql.read_engine.connect() as conn:
            return dict(conn.execute(text(f'SELECT COALESCE(SUM({PAYLOAD_SIZE}),0) AS payload_bytes,'
                f'COALESCE(MAX({PAYLOAD_SIZE}),0) AS maximum_payload_bytes FROM dividend_plan')).mappings().one())
    sizes = await query.mysql.read(size)
    measured = {k: int(v) for k, v in sizes.items()} | dict(source_rows=sum(v['count'] for v in source_periods.values()),
                planned_periods=len(periods), query_p95_upper_ms=max(timings))
    result.update(measured=measured, query_timings_ms=timings, query_digest=baseline,
                  source_digest=digest(source_periods), pipeline_verified=True,
                  strict_proxy_verified=strict_proxy(counts, 1))
    capacity_checks(measured)
    report.update(measurements={**measured, 'sql_rows': len(actual), 'query_p95_ms': max(timings)},
                  limits=LIMITS, conditions='本轮完整冻结股票池，正式来源报告期计划；保留旧历史；原SQLLane连续10次查询最大值',
                  reviewed_tradeoffs='原业务表/索引/来源协议不变；容量通过不代表来源消失的旧方案已裁定，也不替代随机30严格实采')
    result['acceptance_complete'] = True
    report.update(pipeline_verified=True, acceptance_complete=True,
                  strict_proxy_verified=result['strict_proxy_verified'])
