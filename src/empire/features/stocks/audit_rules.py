"""Business-owned stocks.audit_rules."""
from collections import Counter

from empire.features.preparation.evidence import evidence, freshness
from empire.features.stocks.contract import normalize_sina_stock


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
