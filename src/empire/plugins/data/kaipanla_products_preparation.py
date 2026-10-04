"""Range evidence is local to the selected product; unrelated products never gate it."""
from datetime import date

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.collectors.kaipanla_scope import required_days
from empire.plugins.datasets.kaipanla_products import point_count


async def audit(query, request=None):
    scope = PreparationScope.parse(request)
    stocks, calendar = await query.plan()
    selected = [s for s in stocks if not scope.codes or s['code'] in scope.codes]
    absent = set(scope.codes) - {s['code'] for s in selected}
    lower = max(date(2021, 1, 1), date.fromisoformat(scope.start) if scope.start else calendar[0])
    upper = min(calendar[-1], date.fromisoformat(scope.end) if scope.end else calendar[-1])
    days = [d for d in calendar if lower <= d <= upper]
    missing, invalid, count, checked = [], [], 0, 0
    for stock in selected:
        def read():
            with query.mysql.read_engine.connect() as conn:
                return query._records(conn, stock['market'], stock['code'], lower, upper)
        records = await query.mysql.read(read)
        checked += 1
        if len(records) > 10000:
            raise ValueError('证券日核验超限')
        life, covered = None, set()
        for stored in sorted(records, key=lambda r: r['version_observed_at'], reverse=True):
            try:
                row = query._decode(stored, stock['market'], stock['code'])
                life = life or row['lifecycle']
                if life != row['lifecycle']:
                    raise ValueError('上市生命周期改变，需要补采')
                covered.add(stored['trade_date'])
                count += point_count(row)
            except (ValueError, KeyError, TypeError) as exc:
                invalid.append(stock['code'] + '：' + str(exc))
        if life is None:
            missing.append(stock['code'] + ' 缺少有效数据及上市关联')
            break
        exclusions = await query.suspended_days(stock['market'], stock['code'], lower, upper)
        expected = set(required_days({**stock, 'listing_date': life['listing_date']}, days, exclusions))
        gaps = sorted(expected - covered)
        if gaps:
            missing.append(stock['code'] + ' 缺 ' + str(len(gaps)) + ' 日，首个 ' + gaps[0].isoformat())
            break
    complete = bool(selected and days) and checked == len(selected) and not (missing or invalid or absent)
    problems = '；'.join((missing + invalid + (['股票不在当前池'] if absent else []))[:5])
    message = f'本项范围 {lower}～{upper}；核对 {checked}/{len(selected)} 只证券、{count} 个来源点位'
    def evidence(key, ok, note):
        return CheckEvidence(key, 'pass' if ok else 'fail', note)
    return (
        evidence('fields', bool(count) and not invalid, problems or message + '；必需字段与上市关联有效'),
        evidence('keys', bool(count) and not invalid, message + '；来源有序数组、证券日及摘要核对'),
        evidence('coverage', complete, problems or message + '；必要证券日集合完整'),
        evidence('quality', bool(count) and not invalid, PRODUCTS[query.kind].note),
        evidence('freshness', complete, f'按所选范围至 {upper} 核验；未证明的来源错误不当空日'),
        evidence('temporal', scope.purpose == 'analysis',
                 '用于历史来源数据分析；当前股票池有幸存者偏差，未提供当时可用的历史版本'))
