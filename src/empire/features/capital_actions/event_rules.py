"""One eligibility and ambiguity rule for archived distributions and theoretical adjustment."""
from datetime import date
from decimal import Decimal, InvalidOperation

NON_IMPLEMENTED = {'董事会预案', '股东大会预案', '公司预案', '取消分红', '终止'}


class ActionError(ValueError):
    def __init__(self, message, *, day='', identity=''):
        super().__init__(message + (f'（日期 {day}）' if day else '') + (f'（方案 {identity}）' if identity else ''))
        self.day, self.identity = day, identity


def decimal(value, *, positive=False):
    if value is None or isinstance(value, bool):
        raise ActionError('计算必需数值未知，不能填零')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ActionError('计算必需数值格式无效') from None
    if not result.is_finite() or result < 0 or result > Decimal('1e24') or positive and result == 0:
        raise ActionError('计算必需数值必须有效、非负且不越界；价格和因子必须为正')
    return result


def iso(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ActionError('计算日期须为 YYYY-MM-DD') from None
    return value


def actions(dividends, rights, lower, upper, *, include_lower=False, require_shares=True):
    """Do not choose among parallel plans, infer missing components or use proposals."""
    grouped, seen, report_events = {}, set(), {}
    for kind, records in (('dividends', dividends), ('rights', rights)):
        if len(records) > 2000:
            raise ActionError('单证券公司行动超过计算上限')
        for row in records:
            key, data = row['record_key'], row['data']
            if (kind, key) in seen:
                raise ActionError('公司行动业务键重复', identity=key)
            seen.add((kind, key))
            if kind == 'dividends':
                status = data.get('status')
                if status in NON_IMPLEMENTED:
                    continue
                if status != '实施方案':
                    raise ActionError('分红实施状态未知，不能自行裁定', identity=key)
            day = data.get('ex_date')
            if not day:
                raise ActionError('已实施公司行动缺少除权除息日期', identity=key)
            iso(day)
            if kind == 'dividends' and data.get('report_date'):
                report_events.setdefault(data['report_date'], []).append((day, key))
            # Adjustment excludes the normalization base date; nominal cash
            # explicitly includes both endpoints. Neither invents an earlier close.
            if not (lower <= day <= upper if include_lower else lower < day <= upper):
                continue
            group = grouped.setdefault(day, {})
            if kind in group:
                raise ActionError('同日并列方案无法裁定，不能求和或任选一条', day=day, identity=key)
            try:
                values = ([decimal(data.get('cash_per_share')),
                           decimal(data.get('total_bonus_per_share')) if require_shares else None]
                          if kind == 'dividends' else
                          [decimal(data.get('rights_per_share'), positive=True), decimal(data.get('rights_price'), positive=True)])
                if kind == 'dividends' and data.get('tax_basis') != '含税':
                    raise ActionError('现金分红必须明确为每股含税口径')
            except ActionError as exc:
                raise ActionError(str(exc), day=day, identity=key) from None
            group[kind] = (key, values)
    for records in report_events.values():
        if len({day for day, _ in records}) > 1:
            relevant = [(day, key) for day, key in records if (lower <= day <= upper if include_lower else lower < day <= upper)]
            if relevant:
                day, key = relevant[0]
                raise ActionError('同报告期存在不同除息日的实施记录，缺事件关联，不能裁定或重复计入', day=day, identity=key)
    return grouped


