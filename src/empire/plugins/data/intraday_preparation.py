"""Read-only range acceptance for source trend points, never OHLC/second-level claims."""
import json
from datetime import date

from sqlalchemy import text

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.collectors.kaipanla_scope import required_days
from empire.plugins.datasets.intraday import digest, validate


async def audit(query, request=None):
    scope = PreparationScope.parse(request)
    stocks, calendar = await query.plan()
    selected = [s for s in stocks if not scope.codes or s['code'] in scope.codes]
    absent = sorted(set(scope.codes) - {s['code'] for s in selected})
    lower = max(date(2021, 1, 1), date.fromisoformat(scope.start) if scope.start else calendar[0])
    upper = min(calendar[-1], date.fromisoformat(scope.end) if scope.end else calendar[-1])
    days = [d for d in calendar if lower <= d <= upper]
    missing, invalid, count, securities = [], [], 0, 0
    for stock in selected:
        def read():
            with query.mysql.read_engine.begin() as conn:
                return [dict(r) for r in conn.execute(text('SELECT trade_date,payload,content_hash,version_observed_at '
                    'FROM stock_intraday WHERE source=:source AND market=:market AND code=:code '
                    'AND trade_date BETWEEN :start AND :end ORDER BY trade_date LIMIT 10001'),
                    dict(source=query.source, market=stock['market'], code=stock['code'], start=lower, end=upper)).mappings()]
        records = await query.mysql.read(read)
        securities += 1
        if not records:
            missing.append(stock['market'] + ':' + stock['code'] + ' 无已归档证券日及上市关联证据')
            break  # A proven missing security cannot become complete by scanning other securities.
        if len(records) > 10000:
            raise ValueError('分时验收超过有界证券日上限')
        life = None
        covered = set()
        for stored in sorted(records, key=lambda r: r['version_observed_at'], reverse=True):
            try:
                row = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
                validate(row)
                if (row['market'], row['code'], row['trade_date']) != (
                        stock['market'], stock['code'], stored['trade_date'].isoformat()):
                    raise ValueError('证券日关联错误')
                if stored['content_hash'] != digest(row):
                    raise ValueError('内容摘要不一致')
                if life is None:
                    life = row['lifecycle']
                if life != row['lifecycle']:
                    raise ValueError('上市范围关联已改变，需要补采旧证券日')
                covered.add(stored['trade_date'])
                count += len(row['trend']) + len(row['auction'])
            except (ValueError, TypeError, KeyError) as exc:
                invalid.append(stock['code'] + ' / ' + stored['trade_date'].isoformat() + '：' + str(exc))
        if life is None:
            missing.append(stock['code'] + ' 缺少有效上市关联证据')
            break
        excluded = await query.suspended_days(stock['market'], stock['code'], lower, upper)
        expected = set(required_days({**stock, 'listing_date': life['listing_date']}, days, excluded))
        gaps = sorted(expected - covered)
        if gaps:
            missing.append(stock['code'] + ' 缺 ' + str(len(gaps)) + ' 个必要证券日，首个 ' + gaps[0].isoformat())
            break
    complete = bool(selected and days) and not (missing or invalid or absent) and securities == len(selected)
    message = f'范围 {lower}～{upper}，已核对 {securities}/{len(selected)} 只证券、{count} 个来源点位'
    def evidence(key, ok, note):
        return CheckEvidence(key, 'pass' if ok else 'fail', note)
    problems = '；'.join((missing + invalid + ([f'不在当前股票池：{",".join(absent)}'] if absent else []))[:5])
    return (evidence('fields', bool(count) and not invalid, message + '；' + (problems or '必需字段与上市关联有效')),
        evidence('keys', bool(count) and not invalid, message + '；精确分钟键与原顺序竞价点，校验内容摘要及证券日关联'),
        evidence('coverage', complete, problems or message + '；必要证券日集合完整'),
        evidence('quality', bool(count) and not invalid, '价格与来源量结构有效；量单位/来源标记未解释，不推导分钟 OHLC 或成交量'),
        evidence('freshness', complete,
                 f'本次日期上界 {upper}，最近已结束交易日 {calendar[-1]}；不要求范围外日期，旧历史修订回看仍有限制'),
        evidence('temporal', scope.purpose == 'analysis',
                 '可查看历史价格走势；当前股票池有幸存者偏差，只有分钟标签，不能还原秒级信号、逐笔成交或当时可用旧版本'))
