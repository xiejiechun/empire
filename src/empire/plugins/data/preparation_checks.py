"""Read-only business audits for the three current data query plugins.

SQL remains in the data layer. These checks never change archive/fingerprint state.
"""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from empire.contracts.preparation import CheckEvidence
from empire.contracts.stocks import normalize_sina_stock
from empire.core.time import CHINA
from empire.plugins.data.trading_day_cutoff import coverage_as_of, read_trade_day_cutoff
from empire.plugins.datasets.suspensions import FIRST_DATE as SUSPENSION_FIRST_DATE
from empire.plugins.datasets.trade_calendar import FIRST_DATE, month_dates, months_between
from empire.plugins.infra.collection_state import read_state


def evidence(ident, passed, measured):
    return CheckEvidence(ident, 'pass' if passed else 'fail', measured)


def freshness(value, now, label, *, naive_china=False):
    if not value:
        return CheckEvidence('freshness', 'unknown', f'{label}：缺少成功核验时间；内容更新时间不能替代')
    try:
        if not isinstance(value, str) or len(value) < 19:
            raise ValueError('missing time')
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            if not naive_china:
                raise ValueError('missing timezone')
            stamp = stamp.replace(tzinfo=CHINA)
        age = now - stamp
        if age < -timedelta(minutes=5):
            return evidence('freshness', False, f'{label}：核验时间异常超前 {value}')
        if age <= timedelta(days=3):
            return evidence('freshness', True, f'{label}：{stamp.astimezone(CHINA).isoformat()}，不超过 3 天')
        return CheckEvidence('freshness', 'unknown', f'{label} SQL 核验上界 {value} 已超过 3 天；'
                             '缓存命中可能更新了 Redis，本检查未核验缓存，不能确认最新时效')
    except (ValueError, TypeError):
        return evidence('freshness', False, f'{label}：成功核验时间格式不可信')


def audit_stocks(rows, state, now):
    invalid = []
    for row in rows:
        try:
            expected = normalize_sina_stock({'code': row['code'], 'symbol': row['source_symbol'], 'name': row['name']})
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError('identifier mismatch')
        except (ValueError, KeyError, TypeError):
            invalid.append(str(row.get('unified_code', '缺代码')))
    keys = [r['unified_code'] for r in rows]
    symbols = [r['source_symbol'] for r in rows]
    duplicates = len(keys) - len(set(keys)) + len(symbols) - len(set(symbols))
    markets = Counter(r['market'] for r in rows)
    publication = state.get('publication', {})
    count = publication.get('row_count')
    coverage = 0 < len(rows) < 100001 and len(rows) == count and all(markets[m] for m in ('SH', 'SZ', 'BJ'))
    return (
        evidence('fields', bool(rows) and not invalid, f'读取 {len(rows)} 行；字段/格式异常 {len(invalid)} 行；样例：{invalid[:10]}'),
        evidence('keys', bool(rows) and duplicates == 0, f'证券键及来源代码重复合计 {duplicates}；业务键 source + unified_code'),
        evidence('coverage', coverage, f'实际 {len(rows)} / 完整发布 {count}；各市场 {dict(markets)}；限额 100000 行'),
        evidence('quality', bool(rows) and not invalid, f'全量代码/市场/名称规范核验，异常 {len(invalid)}；不代表独立源交叉对账'),
        freshness(state.get('progress', {}).get('finished_at'), now, '股票 SQL 最近确认', naive_china=True),
        evidence('temporal', coverage and bool(publication.get('snapshot_id')) and bool(publication.get('finished_at')),
                 '当前快照与 publication 在同一读取事务核对；' + ('已关联完整发布批次' if publication else '缺少发布批次')),
    )


def check_stocks(plugin):
    with plugin.mysql.read_engine.connect() as conn:
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        rows = conn.execute(text('''SELECT code,name,unified_code,market,source_symbol
            FROM stock WHERE source=:source LIMIT 100001'''), {'source': plugin.source}).mappings().all()
        return audit_stocks(rows, state, datetime.now(CHINA))


def audit_calendar(rows, state, now, *, cache_months=(), cache_note='未读取 Redis 缓存确认'):
    end = f'{now.year + 1}-12'
    months = months_between('1990-12', end)
    expected = {d for month in months for d in month_dates(month)}
    valid = {r['trade_date'] for r in rows if r['is_trade'] in (0, 1)}
    invalid = [r['trade_date'] for r in rows if r['is_trade'] not in (0, 1) or r['trade_date'] < FIRST_DATE]
    missing = expected - valid
    missing_months = Counter(day.strftime('%Y-%m') for day in missing)
    duplicates = len(rows) - len({r['trade_date'] for r in rows})
    observed = state.get('observed', {})
    active = [m for m in months if m >= now.strftime('%Y-%m')]
    stamps = [freshness(observed.get(m), now, m) for m in active]
    stale = [m for m, stamp in zip(active, stamps, strict=True) if stamp.status != 'pass']
    invalid_stamps = [m for m, stamp in zip(active, stamps, strict=True) if stamp.status == 'fail']
    return (
        evidence('fields', bool(rows) and not invalid, f'逐行核验日期与 0/1 标记；无效 {len(invalid)}'),
        evidence('keys', bool(rows) and not duplicates, f'source + trade_date 重复 {duplicates}'),
        evidence('coverage', not missing and len(rows) < 20001,
                 f'目标 {FIRST_DATE} 至 {end}-31，共 {len(expected)} 天；缺 {len(missing)} 天；'
                 f'缺失月份及天数：{dict(sorted(missing_months.items()))}'),
        evidence('quality', bool(rows) and not invalid and not duplicates,
                 f'非法标记/起点前日期 {len(invalid)}；重复 {duplicates}；未按周末推断任何记录'),
        CheckEvidence('freshness', 'fail' if invalid_stamps else 'unknown' if stale else 'pass',
                      f'当前维护区间 {len(active)} 月；可信 Redis 确认 {len(cache_months)} 月；'
                      f'无法证明近 3 天确认的月份 {stale}；异常时间 {invalid_stamps}；{cache_note}；'
                      '其余依据 SQL 确认，不把 SQL 旧上界直接认定停更'),
        CheckEvidence('temporal', 'unknown' if stale else 'pass',
                      '未来安排按当前来源保存，可修订；逐月确认时间' + ('尚缺有效证据' if stale else '有效且不超前')),
    )


def calendar_snapshot(plugin):
    with plugin.mysql.read_engine.connect() as conn:
        rows = conn.execute(text('''SELECT trade_date,is_trade FROM trade_calendar
            WHERE source=:source ORDER BY trade_date LIMIT 20001'''), {'source': plugin.source}).mappings().all()
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        return rows, state


def check_suspensions(plugin):
    now = datetime.now(CHINA)
    with plugin.mysql.read_engine.connect() as conn:
        row = conn.execute(text('''
            SELECT COUNT(*) AS total,
              COUNT(DISTINCT market,code,suspended_at,resume_key,record_key) AS identities,
              MIN(suspended_at) AS earliest,MAX(suspended_at) AS latest,
              SUM(market NOT IN ('SH','SZ') OR code NOT REGEXP '^[0-9]{6}$'
                  OR suspension_type NOT IN ('full_day','intraday') OR TRIM(name)=''
                  OR resumed_at<suspended_at) AS bad,
              COUNT(DISTINCT market) AS markets
              , SUM(source_dates IS NULL OR JSON_TYPE(source_dates)<>'ARRAY'
                    OR JSON_LENGTH(source_dates)=0) AS missing_dates
            FROM suspension_event WHERE source=:source
        '''), {'source': plugin.source}).mappings().one()
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
        try:
            cutoff, calendar_note = read_trade_day_cutoff(conn, now)
        except SQLAlchemyError:
            cutoff, calendar_note = None, '正式交易日历查询失败，不能推断交易日；字段与业务键检查仍独立呈现'
    coverage = state.get('coverage', {})
    from_date, through = coverage.get('from'), coverage.get('through')
    complete = (state.get('collection_integrity_version') == 2
                and from_date == SUSPENSION_FIRST_DATE.isoformat()
                and cutoff is not None and through is not None and through >= cutoff.date().isoformat())
    total, bad = row['total'], (row['bad'] or 0) + (row['missing_dates'] or 0)
    stamp_status, stamp_note = coverage_as_of(coverage, now, cutoff)
    stamp = CheckEvidence('freshness', stamp_status, stamp_note)
    complete &= stamp_status == 'pass'
    return (
        evidence('fields', total > 0 and not bad,
                 f'已存 {total} 条；市场、代码、类型、名称和日期异常 {row["bad"] or 0} 条；'
                 f'缺少来源日期 {row["missing_dates"] or 0} 条'),
        evidence('keys', total > 0 and total == row['identities'],
                 f'{total} 行，唯一业务键 {row["identities"]}；source + market + code + suspended_at + resume_key + record_key'),
        CheckEvidence('coverage', 'pass' if complete else 'unknown' if cutoff is None or stamp_status == 'unknown' else 'fail',
                 f'来源起点 {SUSPENSION_FIRST_DATE}；SQL 连续覆盖 {from_date or "缺少"} ～ {through or "缺少"}；'
                 f'{calendar_note}；事件日期 {row["earliest"]} ～ {row["latest"]}；'
                 '更早历史属于来源限制，休市日或盘中未结束日期不作为已完成日要求'),
        evidence('quality', total > 0 and not bad and row['markets'] == 2,
                 f'字段异常 {bad}；已出现市场数 {row["markets"]}；复牌为空保持未知，临停单独分类'),
        stamp,
        evidence('temporal', total > 0 and not bad,
                 '按停牌和复牌生效时间保存；用于日频成交约束，不将原因文字作为事前信号'),
    )


def check_news(plugin):
    now = datetime.now(CHINA)
    with plugin.mysql.read_engine.connect() as conn:
        row = conn.execute(text('''SELECT COUNT(*) AS total, COUNT(DISTINCT news_id) AS ids,
            MIN(published_at) AS earliest, MAX(published_at) AS latest,
            SUM(news_id<=0 OR TRIM(title)='' OR TRIM(content)='' OR is_important NOT IN (0,1)
                OR JSON_TYPE(tags)<>'ARRAY') AS bad,
            SUM(published_at>source_updated_at OR first_seen_at>version_observed_at
                OR source_updated_at>:latest_allowed OR version_observed_at>:latest_allowed) AS bad_time
            FROM finance_news WHERE source=:source'''), {'source': plugin.source,
                'latest_allowed': (now + timedelta(minutes=5)).replace(tzinfo=None)}).mappings().one()
        state = read_state(conn, plugin.namespace, plugin.project_id, plugin.source)
    total = row['total']
    latest = row['latest'].replace(tzinfo=CHINA) if row['latest'] else None
    now = datetime.now(CHINA)
    timely = latest is not None and -timedelta(minutes=5) <= now - latest <= timedelta(minutes=30)
    return (
        evidence('fields', total > 0 and not row['bad'],
                 f'已存 {total} 条新闻；标题、正文、编号和分类异常 {row["bad"] or 0} 条；只检查新闻本身'),
        evidence('keys', total > 0 and total == row['ids'], f'{total} 行，唯一新闻 ID {row["ids"]}；仅最新版本键'),
        evidence('coverage', total > 0 and state.get('progress', {}).get('status') == 'complete',
                 f'已积累范围 {row["earliest"]} ～ {row["latest"]}；'
                 f'最近保存确认：{state.get("progress", {}).get("status", "缺少")}；'
                 '只证明本项目已有校验后保存的新闻页，不证明以前的新闻已全部补齐'),
        evidence('quality', total > 0 and not row['bad'] and not row['bad_time'],
                 f'空正文/标题/非法分类标记 {row["bad"] or 0}；时间顺序异常 {row["bad_time"] or 0}；全量 SQL 聚合核验'),
        evidence('freshness', timely, f'最新消息 {latest}；超过 30 分钟或未来超前则不满足时效；需核实源端是否停更'),
        evidence('temporal', total > 0 and not row['bad_time'],
                 f'发布时间、当前来源修改时间和观察时间异常 {row["bad_time"] or 0} 条；'
                 '保存当前版本。修改前的旧正文由独立项目负责，本项不宣称能还原历史内容'),
    )
