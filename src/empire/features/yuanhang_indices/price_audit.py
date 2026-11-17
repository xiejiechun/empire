"""Scoped index history checks: range authority is distinct from recent quotes."""
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.preparation import CheckEvidence
from empire.features.yuanhang_indices.audits import evidence
from empire.features.yuanhang_indices.contract import PRICE_PROJECT, digest, number, validate_rows
from empire.features.yuanhang_indices.quality import price_relation_valid, volume_amount_valid
from empire.plugins.infra.collection_state import read_state
from empire.sources.yuanhang_ranges import contiguous_through, validated_segments


def range_covers(segments, year, start, through):
    current = date.fromisoformat(start)
    last = date.fromisoformat(through)
    for first, end, _ in validated_segments(segments, year):
        if end < current:
            continue
        if first > current:
            return False
        if end >= last:
            return True
        current = end + timedelta(days=1)
    return False


def audit_prices(conn, namespace, catalog, scope, through):
    state = read_state(conn, namespace, PRICE_PROJECT, 'ths_yuanhang')
    units = state.get('units', {})
    problems, stats, fresh = [], defaultdict(int), True
    now = datetime.now(UTC)
    for index in catalog:
        code = index['code']
        unit = units.get(code, {})
        stamps = [v for segments in unit.get('price_ranges', {}).values() for _, _, v in segments]
        try:
            latest = max(datetime.fromisoformat(v) for v in stamps)
            fresh &= timedelta(0) <= now-latest <= timedelta(days=3)
        except (ValueError, TypeError):
            fresh = False
        start = scope.start or unit.get('history_start')
        if start and unit.get('history_start'):
            start = max(start, unit['history_start'])
        end = min(scope.end or through, through)
        if not start or state.get('contract_version') != 1:
            problems.append(code + '缺少来源历史起点证明')
            continue
        if start > end:
            # The source started after the requested window; do not invent data.
            stats['outside_source'] += 1
            continue
        heads = {r['quote_year']: dict(r) for r in conn.execute(text(
            'SELECT * FROM yuanhang_index_price_year WHERE index_code=:code AND quote_year BETWEEN :first AND :last LIMIT 151'),
            dict(code=code, first=int(start[:4]), last=int(end[:4]))).mappings()}
        values = conn.execute(text('SELECT trade_date,open,high,low,close,volume,amount FROM yuanhang_index_daily_price '
            'WHERE index_code=:code AND trade_date BETWEEN :first AND :last ORDER BY trade_date LIMIT 54901'),
            dict(code=code, first=start[:4]+'-01-01', last=end[:4]+'-12-31'))
        annual = defaultdict(list)
        for row in values:
            annual[row[0].year].append([row[0].isoformat()] + [number(v) for v in row[1:]])
        if len(heads) > 150 or sum(map(len, annual.values())) > 54900:
            raise ValueError('日K准备检查超过年度容量')
        for year in range(int(start[:4]), int(end[:4])+1):
            head, rows = heads.get(year), annual[year]
            validate_rows(rows, f'{year}-01-01', f'{year}-12-31')
            segments = unit.get('price_ranges', {}).get(str(year), [])
            first, last = max(start, f'{year}-01-01'), min(end, f'{year}-12-31')
            good = (head and head['contract_version'] == 1 and head['native_market'] == index['native_market']
                and unit.get('native_market') == index['native_market']
                and head['content_hash'] == digest(rows) and head['key_hash'] == digest([r[0] for r in rows])
                and head['row_count'] == len(rows)
                and str(head['first_date']) == (rows[0][0] if rows else 'None')
                and str(head['last_date']) == (rows[-1][0] if rows else 'None')
                and (str(head['verified_through']) if head['verified_through'] else None) == contiguous_through(segments, year)
                and range_covers(segments, year, first, last)
                and (bool(scope.start) or str(year) in unit.get('full_years', {})))
            if not good:
                problems.append(f'{code}:{year}范围、正文或完整历史证明不一致')
            for row in rows:
                if not first <= row[0] <= last:
                    continue
                stats['count'] += 1
                stats['missing_close'] += row[4] is None
                stats['missing_ohlc'] += any(v is None for v in row[1:5])
                stats['relations'] += not price_relation_valid(row[1:5])
                stats['missing_quantity'] += any(v is None for v in row[5:])
                stats['negative_quantity'] += not volume_amount_valid(row[5:])
    return problems, stats, fresh


async def price_checks(query, scope):
    try:
        through, _ = await query.scope()
        catalog = await query.catalog(list(scope.index_codes) or None)
        problems, stats, fresh = await query.read(lambda c: audit_prices(c, query.namespace, catalog, scope, through))
        valid = True
    except (ValueError, TypeError, KeyError) as exc:
        valid, problems, stats, fresh = False, [str(exc)], defaultdict(int), False
    note = f"范围内{stats['count']}条日K；{len(problems)}项覆盖问题。" + '；'.join(problems[:10])
    quality = (f"四价缺值{stats['missing_ohlc']}条、价格关系异常{stats['relations']}条、"
        f"量额缺值{stats['missing_quantity']}条、负量额{stats['negative_quantity']}条；保留来源原值。"
        '依赖缺失或异常字段的策略不可用；量额为原生协议口径。')
    return (evidence('fields', valid and stats['count'] > 0 and not stats['missing_close'], note),
        evidence('keys', valid, '指数和日期唯一，年度实际键集合与规范内容摘要核验'),
        evidence('coverage', valid and not problems and stats['count'] > 0, note),
        CheckEvidence('quality', 'pass' if valid and not stats['relations'] and not stats['missing_ohlc'] else 'fail', quality,
            blocking=not valid or scope.purpose != 'analysis', reason='source_limit'),
        evidence('freshness', valid and fresh and not problems, 'SQL可信区间最近核验不超过3天；未以最大日期代替覆盖'),
        CheckEvidence('temporal', 'pass' if scope.purpose == 'analysis' else 'fail',
            '收盘后日线，当前来源修订版；不提供历史可知版本或统一量额口径',
            blocking=scope.purpose != 'analysis', reason='source_limit'))
