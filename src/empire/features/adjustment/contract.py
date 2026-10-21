"""Independent, bounded theoretical ex-rights factors from explicit business inputs."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

ALGORITHM = 'empire-ex-rights-v1'
MAX_DAYS = 3660
MAX_ROWS = 10000
NON_IMPLEMENTED = {'董事会预案', '股东大会预案', '公司预案', '取消分红', '终止'}


class AdjustmentError(ValueError):
    def __init__(self, message, *, day='', identity=''):
        super().__init__(message + (f'（日期 {day}）' if day else '') + (f'（方案 {identity}）' if identity else ''))
        self.day, self.identity = day, identity


def decimal(value, *, positive=False):
    if value is None or isinstance(value, bool):
        raise AdjustmentError('计算必需数值未知，不能填零')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AdjustmentError('计算必需数值格式无效') from None
    if not result.is_finite() or result < 0 or result > Decimal('1e24') or positive and result == 0:
        raise AdjustmentError('计算必需数值必须有效、非负且不越界；价格和因子必须为正')
    return result


def iso(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise AdjustmentError('计算日期须为 YYYY-MM-DD') from None
    return value


def ex_reference(previous_close, cash, shares, rights, rights_price):
    with localcontext() as ctx:
        ctx.prec = 50
        p = decimal(previous_close, positive=True)
        d, s, r, a = (decimal(v) for v in (cash, shares, rights, rights_price))
        if d >= p:
            raise AdjustmentError('含税现金分红不应达到或超过前收盘价，需要核实来源或特殊事件')
        return decimal((p - d + a * r) / (1 + s + r), positive=True)


def actions(dividends, rights, lower, upper):
    """Do not choose among parallel plans, infer missing components or use proposals."""
    grouped, seen, report_events = {}, set(), {}
    for kind, records in (('dividends', dividends), ('rights', rights)):
        if len(records) > 2000:
            raise AdjustmentError('单证券公司行动超过计算上限')
        for row in records:
            key, data = row['record_key'], row['data']
            if (kind, key) in seen:
                raise AdjustmentError('公司行动业务键重复', identity=key)
            seen.add((kind, key))
            if kind == 'dividends':
                status = data.get('status')
                if status in NON_IMPLEMENTED:
                    continue
                if status != '实施方案':
                    raise AdjustmentError('分红实施状态未知，不能自行裁定', identity=key)
            day = data.get('ex_date')
            if not day:
                raise AdjustmentError('已实施公司行动缺少除权除息日期', identity=key)
            iso(day)
            if kind == 'dividends' and data.get('report_date'):
                report_events.setdefault(data['report_date'], []).append((day, key))
            # The first output date is the explicit normalization base. Events
            # on/before it cancel in every ratio; no earlier close is invented.
            if not lower < day <= upper:
                continue
            group = grouped.setdefault(day, {})
            if kind in group:
                raise AdjustmentError('同日并列方案无法裁定，不能求和或任选一条', day=day, identity=key)
            try:
                values = ([decimal(data.get('cash_per_share')), decimal(data.get('total_bonus_per_share'))]
                          if kind == 'dividends' else
                          [decimal(data.get('rights_per_share'), positive=True), decimal(data.get('rights_price'), positive=True)])
                if kind == 'dividends' and data.get('tax_basis') != '含税':
                    raise AdjustmentError('现金分红必须明确为每股含税口径')
            except AdjustmentError as exc:
                raise AdjustmentError(str(exc), day=day, identity=key) from None
            group[kind] = (key, values)
    for records in report_events.values():
        if len({day for day, _ in records}) > 1:
            relevant = [(day, key) for day, key in records if lower < day <= upper]
            if relevant:
                day, key = relevant[0]
                raise AdjustmentError('同报告期存在不同除息日的实施记录，缺事件关联，不能裁定或重复计入', day=day, identity=key)
    return grouped


def calculate(prices, dividends, rights):
    if not prices or len(prices) > MAX_ROWS:
        raise AdjustmentError('原始行情为空或超过计算上限')
    days = [iso(p['date']) for p in prices]
    if days != sorted(set(days)):
        raise AdjustmentError('原始行情日期重复或乱序')
    if (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days > MAX_DAYS:
        raise AdjustmentError('计算日期范围超过3660日')
    groups = actions(dividends, rights, days[0], days[-1])
    missing = sorted(set(groups) - set(days))
    if missing:
        raise AdjustmentError('除权日缺少收盘后行情或处于停牌区间，本版本不推断参考价', day=missing[0])
    result, factor, prior = [], Decimal(1), None
    with localcontext() as ctx:
        ctx.prec = 50
        for item, day in zip(prices, days, strict=True):
            values = {k: decimal(item[k], positive=True) for k in ('open', 'high', 'low', 'close')}
            if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
                raise AdjustmentError('原始行情开收盘不在日高低价区间', day=day)
            group, used, reference = groups.get(day, {}), [], None
            if group:
                cash, shares = group.get('dividends', ('', [Decimal(0), Decimal(0)]))[1]
                ratio, price = group.get('rights', ('', [Decimal(0), Decimal(0)]))[1]
                try:
                    reference = ex_reference(prior, cash, shares, ratio, price)
                except AdjustmentError as exc:
                    raise AdjustmentError(str(exc), day=day) from None
                factor = decimal(factor * prior / reference, positive=True)
                used = [v[0] for v in group.values()]
            result.append(dict(date=day, factor=factor, **values, events=used, reference=reference))
            prior = values['close']
        last = result[-1]['factor']
        for row in result:
            row['forward_multiplier'], row['backward_multiplier'] = row['factor'] / last, row['factor']
            for key in ('open', 'high', 'low', 'close'):
                row['forward_' + key] = row[key] * row['forward_multiplier']
                row['backward_' + key] = row[key] * row['backward_multiplier']
            for key, value in list(row.items()):
                if isinstance(value, Decimal):
                    row[key] = format(value, 'f')
        return result
