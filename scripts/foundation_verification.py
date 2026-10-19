"""Bounded real foundation sources; storage ownership belongs to source_verification."""
import copy
from datetime import date, datetime

from catalogue_verification import observe_fetch, observe_publish, require_drained
from source_verification import digest, require, strict_proxy

from empire.features.calendar.contract import FIRST_DATE as CALENDAR_FIRST
from empire.features.calendar.contract import month_dates, month_start
from empire.features.stocks.contract import normalize_sina_stock
from empire.features.suspensions.contract import FIRST_DATE as SUSPENSION_FIRST
from empire.features.suspensions.contract import event_identity, periods_between
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def same_stocks(expected, actual):
    fields = ('code', 'name', 'unified_code', 'market', 'source_symbol')
    def canonical(rows):
        result = {row['unified_code']: {k: row[k] for k in fields} for row in rows}
        require(len(result) == len(rows), '股票业务键重复')
        return result
    left, right = canonical(expected), canonical(actual)
    require(left == right, '股票来源与正式查询集合或内容不同')
    return left, right


async def routed(operation, counts, proxy_only):
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not proxy_only), ROUTE_COUNTS.set(counts)
    try:
        return await operation()
    finally:
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


async def verify_stocks(manager, source, proxy_only, report):
    capability = 'collector.' + ('sina_universe' if source == 'sina' else 'ths_universe')
    await manager.start(capability)
    collector, query = manager.registry.get(capability), manager.registry.get('stocks.query')
    rows, published, counts = [], [], {}
    result = report['results'][source] = dict(pipeline_verified=False, routes=counts,
                                            published_units=published, scope='complete_current_directory')
    if source == 'sina':
        original = collector._decode_page
        def decode(response):
            value = original(response)
            rows.extend(normalize_sina_stock(row) for row in value)
            return value
        collector._decode_page = decode
    else:
        original = collector.fetch
        async def fetch():
            value = await original()
            rows.extend(copy.deepcopy(value))
            return value
        collector.fetch = fetch
    publish = collector.ingest.publish_page
    enqueued = []
    def check(envelope):
        require(envelope.job_key == collector.job_key, '股票发布者不符')
        if envelope.dataset == 'stock.universe.page':
            enqueued.extend(copy.deepcopy(envelope.raw_payload['rows']))
    collector.ingest.publish_page = observe_publish(publish, check, published)
    try:
        outcome = await routed(lambda: collector.execute(fresh=True, baseline_revision=0), counts, proxy_only)
    finally:
        collector.ingest.publish_page = publish
        if source == 'sina':
            collector._decode_page = original
        else:
            collector.fetch = original
    require(outcome['expected_count'] == len(rows) == outcome['collected'], '股票来源总数不符')
    same_stocks(rows, enqueued)
    actual, offset = [], 0
    while True:
        page = await query.list_stocks(offset=offset, limit=500)
        actual.extend(page['rows'])
        require(page['total'] == len(rows), '股票正式总数不符')
        if len(actual) >= page['total']:
            break
        require(bool(page['rows']) and len(actual) <= 100000, '股票分页停滞')
        offset += len(page['rows'])
    canonical_source, canonical_query = same_stocks(rows, actual)
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, 1),
                  acceptance_complete=True, source_count=len(rows),
                  source_digest=digest(canonical_source), query_digest=digest(canonical_query),
                  public_query_equal=True, pending=await require_drained(manager), outcome=outcome,
                  limitations='完整当前目录；非逐股票请求，不声明随机30股门槛')


def calendar_plan(months):
    require(bool(months) and months == sorted(set(months)) and len(months) <= 24, '日历范围须有序唯一且不超过24月')
    for month in months:
        month_start(month)
        require(month >= CALENDAR_FIRST.strftime('%Y-%m'), '日历范围早于来源起点')
    return dict(months=months, maintenance_start=months[0], end_month=months[-1],
                expected_count=sum(len(month_dates(month)) for month in months))


async def verify_calendar(manager, months, proxy_only, report):
    plan = calendar_plan(months)
    await manager.start('collector.cninfo_calendar')
    collector, query = manager.registry.get('collector.cninfo_calendar'), manager.registry.get('calendar.query')
    sources, published, counts = {}, [], {}
    result = report['results']['calendar'] = dict(pipeline_verified=False, routes=counts,
        published_units=published, finite_plan=plan,
        scope='explicit verifier-only plan; unchanged production collector and archive')
    original_plan, download, publish = query.plan, collector.download, collector.ingest.publish_page
    async def bounded_plan(today, fresh=False):
        return copy.deepcopy(plan)
    def remember(args, value):
        require(args[0] not in sources, '日历月份重复')
        sources[args[0]] = value
    def check(envelope):
        payload = envelope.raw_payload
        require(envelope.dataset == 'calendar.month' and payload['rows'] == sources[payload['month']],
                '日历来源与入队集合或内容不同')
    query.plan = bounded_plan
    collector.download = observe_fetch(download, remember)
    collector.ingest.publish_page = observe_publish(publish, check, published)
    try:
        outcome = await routed(lambda: collector.execute(fresh=True, baseline_revision=0), counts, proxy_only)
    finally:
        query.plan, collector.download, collector.ingest.publish_page = original_plan, download, publish
    require(set(sources) == set(months) and len(published) == len(months), '日历月份集合不同')
    for month, rows in sources.items():
        actual = await query.month(month)
        require(actual['complete'] and [{k: row[k] for k in ('trade_date', 'is_trade')}
                for row in actual['rows']] == rows, '日历正式查询集合或内容不同')
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(months)),
                  acceptance_complete=True, source_units={m: dict(count=len(r), digest=digest(r))
                  for m, r in sources.items()}, public_query_equal=True,
                  pending=await require_drained(manager), outcome=outcome,
                  limitations='限定整月，不代表全部历史已采完；日历非股票采集粒度')


def suspension_plan(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    require(first == SUSPENSION_FIRST, '空私有库必须从停复牌来源起点初始化；不能伪造既往覆盖')
    require(0 <= (last-first).days <= 62, '停复牌验证范围须为1至63个自然日')
    return dict(periods=periods_between(first, last), start_date=start, end_date=end,
                expected_days=(last-first).days+1, coverage_through=None)


def suspension_differences(sources):
    seen, differences = {}, []
    for day in sorted(sources):
        for row in sources[day]:
            key = event_identity(row)
            if key in seen and seen[key][1] != row:
                previous_day, previous = seen[key]
                differences.append(dict(identity=key, previous_day=previous_day, day=day,
                    fields={k: [previous[k], row[k]] for k in row if previous[k] != row[k]}))
            seen[key] = (day, row)
    return differences


def same_suspensions(expected, actual):
    def normalized(row):
        return {k: (datetime.fromisoformat(row[k]).replace(tzinfo=None).isoformat(timespec='minutes')
                    if k in ('suspended_at', 'resumed_at') and row[k] else row[k]) for k in row}
    left, right = [normalized(r) for r in expected], [normalized(r) for r in actual]
    require(sorted(left, key=repr) == sorted(right, key=repr), '停复牌来源日正式查询集合或内容不同')


async def verify_suspensions(manager, start, end, proxy_only, report):
    plan = suspension_plan(start, end)
    await manager.start('collector.tdx_suspensions')
    collector, query = manager.registry.get('collector.tdx_suspensions'), manager.registry.get('suspensions.query')
    sources, counts, published = {}, {}, []
    result = report['results']['suspensions'] = dict(pipeline_verified=False, routes=counts,
        finite_plan=plan, source_units={}, published_units=published,
        fixed_error_id='38622b7215a44fe4a5224031bdf4d963')
    # Observe the exact unresolved dates independently. Their modern contents
    # must not be given fabricated historical coverage in this empty database.
    fixed = {}
    async def probe_fixed():
        for day in ('2026-10-19', '2026-10-20'):
            rows, requests = await collector._collect_day(day)
            fixed[day] = rows
            result.setdefault('fixed_date_observation', {})[day] = dict(
                count=len(rows), digest=digest(rows), requests=requests,
                fixed_security=[r for r in rows if r['market']=='SH' and r['code']=='603517'])
        result['fixed_date_conflicts'] = suspension_differences(fixed)
        result['fixed_date_limitations'] = ('只读来源复核，未归档到此空私有库；既有错误未修复、不清ID；'
                                          '本轮正式全链路范围为下列来源起点日期')
    await routed(probe_fixed, counts, proxy_only)
    original_plan, collect, publish = query.plan, collector._collect_day, collector.ingest.publish_page
    async def bounded_plan(today, fresh=False):
        return copy.deepcopy(plan)
    async def observe_day(day, **kwargs):
        value = await collect(day, **kwargs)
        require(day not in sources, '停复牌来源日期重复')
        sources[day] = copy.deepcopy(value[0])
        result['source_units'][day] = dict(count=len(value[0]), digest=digest(value[0]), requests=value[1])
        result['source_content_conflicts'] = suspension_differences(sources)
        return value
    envelopes = []
    def check(envelope):
        require(envelope.dataset == 'suspensions.period', '停复牌数据集错误')
        envelopes.append(copy.deepcopy(envelope.raw_payload))
    query.plan, collector._collect_day = bounded_plan, observe_day
    collector.ingest.publish_page = observe_publish(publish, check, published)
    try:
        outcome = await routed(lambda: collector.execute(fresh=True, baseline_revision=0), counts, proxy_only)
    finally:
        query.plan, collector._collect_day, collector.ingest.publish_page = original_plan, collect, publish
    require(len(sources) == plan['expected_days'], '停复牌来源日期不完整')
    for day, rows in sources.items():
        actual = await query.list_events(start=day, end=day, limit=500)
        same_suspensions(rows, actual)
    require(bool(envelopes), '停复牌未入队')
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(sources)),
                  acceptance_complete=True, pending=await require_drained(manager), outcome=outcome,
                  public_query_equal=True, limitations='限定自然日整响应；非逐股票采集，不证明全历史完整')
