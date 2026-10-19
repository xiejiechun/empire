"""On-demand factors and adjusted prices from one immutable archived-input snapshot."""
from datetime import UTC, date, datetime, timedelta

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, ComputationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import unified_code
from empire.core.time import CHINA
from empire.features.adjustment.contract import ALGORITHM, MAX_DAYS, AdjustmentError, calculate, iso
from empire.features.adjustment.inputs import close_prices, events
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.capital_actions.contract import digest


def resolve_security(conn, market, code):
    from sqlalchemy import bindparam, text
    candidates = [unified_code(m, code) for m in ('SH', 'SZ', 'BJ')]
    sql = text('SELECT unified_code FROM stock WHERE unified_code IN :keys ORDER BY unified_code').bindparams(
        bindparam('keys', expanding=True))
    matches = list(conn.execute(sql, dict(keys=candidates)).scalars())
    if market == 'AUTO':
        if len(matches) != 1:
            raise AdjustmentError('股票代码在当前目录中不存在或市场不唯一，请明确选择SH/SZ/BJ')
        return matches[0]
    security = unified_code(market, code)
    if len(matches) == 1 and matches[0] != security:
        raise AdjustmentError(f'{code}属于{matches[0][-2:]}市场，当前选择{market}；请选择自动识别或正确市场')
    return security


class AdjustmentDataPlugin:
    manifest = PluginManifest('data.adjustment', '自算复权因子与行情',
        requires=('mysql.store', 'kaipanla_quote.query'), provides=('adjustment.query',),
        description='只读已归档分红送转、配股及收盘价；缺输入和方案歧义不生成因子')
    output_version = ALGORITHM
    preparation = tuple(ComputationContribution(requirement, 'adjustment.query', '自算：通达信事件 / 开盘啦价格',
        'empire-' + requirement.replace('_', '-'), ('tests/test_adjustment.py', 'tests/test_adjustment_query.py'),
        ('tests/integration/test_adjustment_pipeline.py',), ALGORITHM,
        page_id='adjustment',
        method='preparation_check' if requirement == 'adjustment_factors' else 'prices_preparation_check')
        for requirement in ('adjustment_factors', 'adjusted_prices'))

    def __init__(self, namespace='empire'):
        self.namespace, self.mysql, self.quotes = namespace, None, None

    async def start(self, context):
        self.mysql, self.quotes = context.get('mysql.store'), context.get('kaipanla_quote.query')
        return {'adjustment.query': self}

    def _calculate(self, market, code, start, end):
        return self._history(market, code, start, end, require_adjustment=True)

    def _history(self, market, code, start, end, *, require_adjustment=False):
        lower, upper = date.fromisoformat(iso(start)), date.fromisoformat(iso(end))
        if lower < date(2021, 1, 1) or lower > upper or (upper-lower).days > MAX_DAYS:
            raise AdjustmentError('现有行情支持2021年起；起止须有序且最多3660日')
        with self.mysql.read_engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            security = resolve_security(conn, market, code)
            market, code = security[-2:], security[:6]
            cutoff, problem = read_trade_day_cutoff(conn, datetime.now(CHINA))
            if cutoff is None:
                raise AdjustmentError(problem)
            if upper > cutoff.date():
                from sqlalchemy import text
                future_trade = conn.execute(text('SELECT 1 FROM trade_calendar WHERE trade_date>:cutoff '
                    'AND trade_date<=:upper AND is_trade=1 LIMIT 1'), dict(cutoff=cutoff.date(), upper=upper)).first()
                if upper > datetime.now(CHINA).date() or future_trade:
                    raise AdjustmentError('范围包含尚未结束的交易日，请缩短计算范围')
            prices = close_prices(conn, self.quotes, market, code, lower, upper)
            problem, observed, event_plans = '', [], {}
            try:
                dividends, rights, observed = events(conn, self.namespace, market, code)
                event_plans = {r['record_key']: kind for kind, records in (('dividends', dividends), ('rights_issues', rights)) for r in records}
                rows = calculate(prices, dividends, rights)
                checksum = digest([ALGORITHM, security, start, end, prices, dividends, rights])
            except (ValueError, KeyError, TypeError) as exc:
                if require_adjustment:
                    raise
                problem = str(exc)
                # Validate raw candles separately for display. Invalid days
                # stay explicit gaps; no price is inferred or used in factors.
                rows = []
                gaps = []
                for price in prices:
                    try:
                        rows.extend(calculate([price], [], []))
                    except (ValueError, KeyError, TypeError) as price_exc:
                        gaps.append(price['date'] + '：' + str(price_exc))
                        row = dict(date=price['date'], events=[], factor=None, reference=None,
                                   forward_multiplier=None, backward_multiplier=None)
                        row.update({prefix+key: None for prefix in ('', 'forward_', 'backward_')
                                    for key in ('open', 'high', 'low', 'close')})
                        rows.append(row)
                if gaps:
                    problem += '；原始K线缺口：' + '；'.join(gaps[:10]) + f'（共{len(gaps)}日）'
                for row in rows:
                    for key in tuple(row):
                        if key in ('factor', 'reference') or key.startswith(('forward_', 'backward_')):
                            row[key] = None
                checksum = digest([ALGORITHM, security, start, end, prices, 'raw-only'])
        return dict(rows=rows, security=security, start=start, end=end, base_date=rows[0]['date'],
            anchor_date=rows[-1]['date'], input_hash=checksum, algorithm_version=ALGORITHM,
            observed_at=min(observed).isoformat() if observed else None,
            adjustment_problem=problem,
            event_plans=event_plans,
            limitations='区间首日归一为1；理论参考价不舍入；当前来源修订版，不证明当时可知版本；'
                         '仅分红送转及配股，不处理合并换股等其他事件；复权价不用于成交和现金记账')

    async def calculate(self, market, code, start, end):
        return await self.mysql.read(self._calculate, market, code, start, end)

    async def history(self, market, code, start, end):
        return await self.mysql.read(self._history, market, code, start, end)

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        identifiers = ('fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal')
        if not scope.codes or not scope.start or not scope.end or len(scope.codes) > 20:
            return tuple(CheckEvidence(k, 'unknown', '自算项目请指定1～20只证券及起止日期；不默认扫描全市场历史') for k in identifiers)
        def resolve():
            from sqlalchemy import bindparam, text
            with self.mysql.read_engine.connect() as conn:
                sql = text('SELECT unified_code FROM stock WHERE LEFT(unified_code,6) IN :codes '
                           'ORDER BY unified_code LIMIT 61').bindparams(bindparam('codes', expanding=True))
                return list(conn.execute(sql, dict(codes=list(scope.codes))).scalars())
        securities = await self.mysql.read(resolve)
        if len(securities) != len(scope.codes) or {s[:6] for s in securities} != set(scope.codes):
            return tuple(CheckEvidence(k, 'fail', '指定证券不在当前目录或跨市场身份不唯一；请在复权页面明确市场') for k in identifiers)
        results = []
        for security in securities:
            try:
                results.append(await self.calculate(security[-2:], security[:6], scope.start, scope.end))
            except (AdjustmentError, ValueError, KeyError, TypeError) as exc:
                findings = (dict(security=security, date=getattr(exc, 'day', ''), identity=getattr(exc, 'identity', ''), message=str(exc)),)
                return tuple(CheckEvidence(k, 'fail', security + '：' + str(exc), findings=findings) for k in identifiers)
        message = f'核实{len(results)}只证券，共{sum(len(r["rows"]) for r in results)}个交易日；输入完整集合、摘要和计算规则通过'
        fresh = all(datetime.fromisoformat(r['observed_at']) >= datetime.now(UTC)-timedelta(days=3) for r in results)
        return tuple(CheckEvidence(k, 'pass', message) for k in identifiers[:4]) + (
            CheckEvidence('freshness', 'pass' if fresh else 'fail', '事件完整证明在三日内' if fresh else '事件完整证明过期，请先核验事件来源再重算'),
            CheckEvidence('temporal', 'pass' if scope.purpose == 'analysis' else 'fail',
                          '截止日固定；当前来源修订版本，只支持普通分析，不证明过去可知的方案和行情版本'))

    async def prices_preparation_check(self, request=None):
        return await self.preparation_check(request)

    async def stop(self):
        self.mysql = self.quotes = None

    def health(self):
        return dict(status='ok' if self.mysql else 'stopped', algorithm=ALGORITHM)
