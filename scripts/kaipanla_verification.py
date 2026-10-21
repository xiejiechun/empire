"""Observe unchanged KPL execution; never write source databases or fabricate coverage."""
import copy
from datetime import date, datetime, timedelta

from catalogue_verification import observe_publish, require_drained
from foundation_verification import routed
from source_verification import digest, require, strict_proxy
from sqlalchemy import bindparam, text

from empire.contracts.security import split_unified_code
from empire.core.config import default_config_path, load_config
from empire.core.time import CHINA
from empire.features.calendar.contract import month_dates
from empire.features.kaipanla import collector as collector_module
from empire.features.kaipanla import download as download_module
from empire.features.kaipanla.contract import PRODUCTS
from empire.features.kaipanla.dates import lifecycle, required_days
from empire.features.kaipanla.normalization import digest as business_digest
from empire.features.kaipanla.normalization import point_count
from empire.features.kaipanla.storage_contract import SERIES
from empire.features.suspensions.exclusions import excluded_days
from empire.plugins.infra.mysql_store import make_engine

FIXED_CODES = ('002731.SZ', '920112.BJ', '920175.BJ', '920304.BJ', '605333.SH')


def checked_days(values):
    require(bool(values) and len(values) <= 5 and values == sorted(set(values)), '日期须有序唯一且为1至5日')
    result = [date.fromisoformat(value) for value in values]
    require(all(day.isoformat() == value and date(2021, 1, 1) <= day < datetime.now(CHINA).date()
                for day, value in zip(result, values, strict=True)), '日期须为2021年以来已结束的历史日')
    return result


def reference_scope(config_path, securities, days):
    """Read finite dependencies in one production READ ONLY snapshot.

    Exact snapshot hashes and scope are reported, without claiming historical
    suspension-source completeness or fabricating private history coverage.
    """
    engine = make_engine(load_config(config_path)['mysql'])
    months, calendar = sorted({day.strftime('%Y-%m') for day in days}), []
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            server = conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
            for month in months:
                expected = month_dates(month)
                rows = [dict(row) for row in conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
                    'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date'),
                    dict(start=expected[0], end=expected[-1])).mappings()]
                require([row['trade_date'] for row in rows] == expected and
                        all(row['is_trade'] in (0, 1) for row in rows), '正式日历月份缺日或异常')
                calendar.extend(rows)
            flags = {row['trade_date']: row['is_trade'] for row in calendar}
            require(all(flags[day] == 1 for day in days), '所选日期不是正式交易日')
            statement = text('SELECT unified_code,suspended_at,resumed_at,suspension_type,source_note '
                'FROM suspension_event WHERE unified_code IN :securities AND suspended_at<:end '
                'AND (resumed_at>:start OR (resumed_at IS NULL AND suspended_at>=:start)) '
                'ORDER BY unified_code,suspended_at LIMIT 100001').bindparams(bindparam('securities', expanding=True))
            events = [dict(row) for row in conn.execute(statement, dict(securities=securities,
                start=min(days), end=max(days)+timedelta(days=1))).mappings()]
            require(len(events) <= 100000, '停牌参考范围超过有界上限')
            conn.rollback()
    finally:
        engine.dispose()
    return events, dict(server_uuid=server, read_only=True, months=months,
        calendar_digest=digest([{**r, 'trade_date': r['trade_date'].isoformat()} for r in calendar]),
        suspension_count=len(events), suspension_digest=digest([
            {k: v.isoformat() if isinstance(v, (date, datetime)) else v for k, v in r.items()} for r in events]),
        limitations='正式SQL有限依赖快照，不证明停复牌全部历史来源完整，也不生成空库历史覆盖')


def unit(code, day):
    return code + '/' + day.isoformat()


def random_coverage(result, random_codes):
    """A valid pipeline with honest source gaps is not thirty successful stocks."""
    expected = set(result['expected_units'])
    sources, queries = result['source_units'], result['query_units']
    details = {}
    for code in random_codes:
        units = {key for key in expected if key.split('/')[0] == code}
        verified = {key for key in units if key in sources and key in queries
                    and sources[key] == queries[key] and key not in result['failures']}
        details[code] = dict(expected=len(units), verified=len(verified))
    return dict(complete=len(details) >= 30 and all(
        value['expected'] > 0 and value['verified'] == value['expected'] for value in details.values()),
        stocks=details)


def compare_payload(envelope, sources, listings, kind):
    require(envelope.dataset == 'kaipanla.' + kind + '.day', '入队数据集改变')
    require(len(envelope.raw_payload['rows']) == 1, '证券日入队粒度改变')
    row = envelope.raw_payload['rows'][0]
    code = row['code'] + '.' + row['market']
    key = unit(code, date.fromisoformat(row['trade_date']))
    require(key in sources and code in listings, '入队包含未观察的来源或上市身份')
    expected = {**sources[key], 'market': row['market'], 'lifecycle': lifecycle(listings[code])}
    require(row == expected, '来源规范内容/上市关联与Redis入队不同')
    return key, copy.deepcopy(row)


async def verify_kind(manager, kind, selected, days, events, proxy_only, result, bounded_request=False):
    await manager.start('collector.kaipanla_' + kind)
    collector = manager.registry.get('collector.kaipanla_' + kind)
    query = collector.query
    stocks = [dict(row, market=split_unified_code(row['unified_code'])[0],
                   code=split_unified_code(row['unified_code'])[1]) for row in selected]
    wanted = {row['unified_code'] for row in selected}
    exclusions = excluded_days([row for row in events if row['unified_code'] in wanted],
                               wanted, days[0], days[-1])
    sources, failures, listings, enqueued, counts, published = {}, {}, {}, {}, {}, []
    result.update(pipeline_verified=False, acceptance_complete=False, routes=counts,
                  days=[day.isoformat() for day in days], selected=sorted(wanted),
                  published_units=published, failures=failures)
    plan, suspension, consume, attach, publish = (query.plan, query.suspension_plan,
        download_module.consume, collector_module.attach_listing_dates, collector.ingest.publish_page)

    async def bounded_plan():
        return copy.deepcopy(stocks), list(days)

    async def bounded_suspension(actual, start, end):
        require({s['code'] + '.' + s['market'] for s in actual} <= wanted and
                (start, end) == (days[0], days[-1]), '停牌规划超出冻结范围')
        return {s['code'] + '.' + s['market']: exclusions[s['code'] + '.' + s['market']] for s in actual}

    async def observe_listing(owner, values):
        value = await attach(owner, values)
        require(owner is collector, '上市观察器拥有者错误')
        listings.update({s['code'] + '.' + s['market']: copy.deepcopy(s) for s in value})
        return value

    async def observe_consume(owner, response, stock, day):
        key = unit(stock['code'] + '.' + stock['market'], day)
        require(owner is collector and key not in sources and key not in failures, '来源单元重复或拥有者错误')
        try:
            value = await consume(owner, response, stock, day)
        except Exception as exc:
            failures[key] = dict(type=type(exc).__name__, category=getattr(exc, 'category', None),
                                 message=collector.records.sanitize_text(exc))
            raise
        sources[key] = copy.deepcopy(value)
        return value

    def check(envelope):
        key, row = compare_payload(envelope, sources, listings, kind)
        require(key not in enqueued, '证券日重复发布')
        enqueued[key] = row

    state = await collector.ingest.checkpoint(collector.job_key)
    query.plan, query.suspension_plan = bounded_plan, bounded_suspension
    download_module.consume, collector_module.attach_listing_dates = observe_consume, observe_listing
    collector.ingest.publish_page = observe_publish(publish, check, published)
    try:
        try:
            options = {'request':dict(securities=sorted(wanted), start=days[0].isoformat(),
                end=days[-1].isoformat(), proxy_priority=False)} if bounded_request else {}
            result['execution_request'] = options.get('request')
            result['outcome'] = await routed(lambda: collector.execute(fresh=True,
                baseline_revision=state['revision'], **options), counts, proxy_only)
        except Exception as exc:
            result['execution_error'] = dict(type=type(exc).__name__, message=collector.records.sanitize_text(exc))
    finally:
        query.plan, query.suspension_plan = plan, suspension
        download_module.consume, collector_module.attach_listing_dates = consume, attach
        collector.ingest.publish_page = publish
    expected = {unit(code, day) for code, stock in listings.items()
                for day in required_days(stock, days, exclusions[code])}
    require(set(sources) | set(failures) == expected, '来源单元集合不符，不能按条数判断完整')
    require(set(enqueued) == set(sources), '有效来源与Redis入队集合不同')
    comparisons = {}
    for key in sorted(expected):
        code, stamp = key.split('/')
        market, number = split_unified_code(code)
        actual = await query.day(market, number, stamp)
        if key in failures:
            require(actual is None, '无有效来源的单元出现伪造数据')
            continue
        require(actual is not None and actual['data'] == enqueued[key], '正式日查询集合或内容不同')
        row = actual['data']
        if kind in SERIES:
            points, seqs, cursor, seen = [], [], None, set()
            while True:
                page = await query.page(market, number, stamp, cursor)
                points.extend(page['points'])
                seqs.extend(page['seqs'])
                cursor = page['next_cursor']
                if cursor is None:
                    break
                token = repr(cursor)
                require(token not in seen and len(points) <= 100000, '正式分页停滞或越界')
                seen.add(token)
            require(points == row['data'][PRODUCTS[kind].field] and seqs == list(range(point_count(row))),
                    '正式分页序号、集合或内容不同')
        comparisons[key] = dict(digest=business_digest(row), points=point_count(row))
    cursor = (await collector.ingest.checkpoint(collector.job_key))['cursor']
    complete = not failures and not result.get('execution_error') and cursor.get('phase') == 'complete'
    require(complete or cursor.get('phase') != 'complete', '来源失败却推进完整断点')
    result.update(pipeline_verified=bool(expected) and len(comparisons) == len(sources),
        acceptance_complete=complete, strict_proxy_verified=strict_proxy(counts, len(expected)),
        # Include the independently checked listing/market association in both
        # hashes; the parsed response alone has no market/lifecycle fields.
        source_units={k: dict(digest=business_digest(enqueued[k]), points=point_count(v))
                      for k, v in sources.items()},
        query_units=comparisons, public_query_equal=True, cursor=cursor,
        excluded={k: sorted(d.isoformat() for d in v) for k, v in exclusions.items()},
        expected_units=sorted(expected), pending=await require_drained(manager),
        limitations='明确证券/历史日；验证器仅限制规划，正式采集/解析/入队/归档/查询不变；来源缺口不转为空日')


def prepare_reference(selection, args, report):
    require(args.kinds and len(set(args.kinds)) == len(args.kinds), '产品种类重复或为空')
    days, fixed_days = checked_days(args.days), checked_days(args.fixed_days)
    selected = selection['selected']
    events, proof = reference_scope(args.pool_config or default_config_path(),
        sorted(s['unified_code'] for s in selected), sorted(set(days + fixed_days)))
    require(proof['server_uuid'] == report['source_server_uuid'], '来源参考实例与冻结股票池实例不同')
    report['reference_snapshot'] = proof
    return events


async def verify_scope(manager, selection, args, report, events):
    days, fixed_days = checked_days(args.days), checked_days(args.fixed_days)
    selected = selection['selected']
    require(report['reference_snapshot']['server_uuid'] != report['storage']['server_uuid'],
            '来源参考与私有库实例相同')
    report['applicability'] = '明确产品及有限日期；随机30和原五固定反例，旧历史失败独立保留'
    for kind in args.kinds:
        for name, stocks, scope_days in [('random_and_fixed', selected, days),
                ('historical_fixed', [s for s in selected if s['unified_code'] in FIXED_CODES], fixed_days)]:
            result = report['results'][kind + '/' + name] = {}
            await verify_kind(manager, kind, stocks, scope_days, events, args.proxy_only, result,
                              getattr(args, 'bounded_request', False))
            if name == 'random_and_fixed':
                result['random_coverage'] = random_coverage(result, selection['random'])
                result['random_samples_complete'] = result['random_coverage']['complete']
            else:
                main = report['results'][kind + '/random_and_fixed']
                result['random_samples_complete'] = main['random_samples_complete']
                result['random_samples_evidence'] = kind + '/random_and_fixed'
