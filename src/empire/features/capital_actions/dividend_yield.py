"""Interval nominal cash yield; no writes, alternate prices or historical signals."""
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.distribution import amount_text, distribution_result
from empire.features.capital_actions.event_rules import ActionError, actions
from empire.features.capital_actions.preparation import optional_evidence, snapshot_units
from empire.features.capital_actions.yield_inputs import calendar_days, denominator_day, price_input

VERSION = 'interval-nominal-dividend-yield-v1'
LIMITATIONS = ['名义每股含税派息除以期末未复权价格，不是到账现金、持仓收益、年化或TTM。',
    '当前来源修订版，用于事后分析；缺逐次修订可用日期，不用于历史可知信号。',
    '股本基准由区间逐交易日来源快照核对，不证明日内变动或全部历史版本；送转或基准变化不计算简版。',
    '不含持仓资格、支付日、税费、再投资、回购及稀释计算。']


def yield_number(cash, price):
    with localcontext() as ctx:
        ctx.prec = 60
        from empire.features.capital_actions.event_rules import decimal
        return amount_text(decimal(cash) / decimal(price, positive=True) * Decimal(100))


def snapshot(plugin, scope):
    with plugin.mysql.read_engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        conn.exec_driver_sql('START TRANSACTION READ ONLY')
        checks, verified, units = snapshot_units(plugin, scope, conn)
        inputs, problem = {}, ''
        try:
            now = datetime.now(UTC)
            day = denominator_day(conn, scope.end, now)
            lower, end = date.fromisoformat(scope.start), date.fromisoformat(scope.end)
            expected, calendar = calendar_days(conn, plugin.namespace, lower, end, day, now)
            quotes = plugin.context.optional('kaipanla_quote.query') if plugin.context else None
            for security, rows in units.items():
                groups = actions(rows, [], scope.start, scope.end, include_lower=True)
                if any(group['dividends'][1][1] != 0 for group in groups.values()):
                    raise ActionError('区间含送转，股数基准变化，简版股息率不可比')
                inputs[security] = dict(calendar=calendar,
                    denominator=price_input(conn, quotes, security, lower, end, day, expected, now, plugin.namespace))
        except (ActionError, ValueError, TypeError, KeyError) as exc:
            inputs, problem = {}, str(exc)
        conn.rollback()
        return checks, verified, units, inputs, problem


async def calculate_yield(plugin, request):
    scope = PreparationScope.parse(request)
    if not scope.codes or len(scope.codes) > 20 or not scope.start or not scope.end:
        raise ValueError('区间名义现金股息率须指定1～20只证券及起止日期')
    checks, verified, units, inputs, problem = await plugin.mysql.read(snapshot, plugin, scope)
    checks = await optional_evidence(plugin, checks, verified)
    result = distribution_result(scope, checks, units)
    result.update(id='dividend_yield', title='区间名义现金股息率', version=VERSION, unit='%',
        formula='Y = Σ闭区间实施每股含税派息 / 截止日对应最近已结束交易日未复权收盘价 × 100%',
        limitations=LIMITATIONS.copy())
    result.pop('input_hash', None)
    if result['state'] != '已计算':
        return result
    if problem or set(inputs) != set(units):
        result.update(state='数据阻断', problem=problem or '多输入证券身份集合不完整', securities=[])
        result['checks'].append(asdict(CheckEvidence('fields', 'fail', result['problem'])))
        return result
    for item in result['securities']:
        source = inputs[item['security']]
        item.update(source)
        item['yield_percent'] = yield_number(item['cash_per_share'], source['denominator']['price'])
    result['checks'].append(asdict(CheckEvidence('fields', 'pass',
        '同一只读SQL快照：完整分红、正式日历、未复权收盘后证券日和停复牌；逐交易日股本基准一致。')))
    result['input_hash'] = digest([VERSION, asdict(scope), units, inputs, result['observed_at']])
    return result


async def preparation_check(plugin, request=None):
    scope = PreparationScope.parse(request)
    if not scope.codes or not scope.start or not scope.end:
        return (CheckEvidence('coverage', 'unknown', '须指定证券及区间后检查区间名义现金股息率'),)
    result = await calculate_yield(plugin, request)
    status = 'pass' if result['state'] == '已计算' else 'fail'
    return tuple(CheckEvidence(k, status, result.get('problem') or result['formula'],
        observed_at=result['observed_at'], reason='source_limit' if result['state'] == '来源受限' else '')
        for k in ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'))
