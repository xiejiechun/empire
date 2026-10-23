"""Verified native history fields and typed normalization, without I/O.

Sparse capital series retain their own effective dates. Unknown/unsupported
fields and missing required values fail closed; no inferred empty histories.
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .yuanhang_wire import validate_history_tables

DAILY_FIELDS = frozenset({1, 7, 8, 9, 11, 13, 19})
ACTION_FIELDS = frozenset({1, 454, 455, 456, 460, 463})
CAPITAL_FIELDS = {402: 'total', 407: 'circulating', 380: 'free_float'}
MARKETS = {'SH': 'USHA', 'SZ': 'USZA', 'BJ': 'USTM'}


def security_identity(unified_code: str) -> str:
    if not isinstance(unified_code, str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', unified_code):
        raise ValueError('Yuanhang requires a unified SH/SZ/BJ security code')
    code, market = unified_code.split('.')
    return MARKETS[market] + code


def day_number(value: date) -> int:
    if type(value) is not date:
        raise ValueError('Yuanhang history boundary must be a date')
    return value.year * 10000 + value.month * 100 + value.day


def _date(value: int) -> date:
    return date(value // 10000, value // 100 % 100, value % 100)


def _number(value, *, label: str, precision: int = 28, scale: int = 10) -> Decimal:
    # str(float) preserves the decoded binary64's shortest round-trip decimal.
    # Never round values to fit SQL: an unexplained extra digit needs investigation.
    if type(value) not in (int, float, Decimal):
        raise ValueError(f'Yuanhang missing or invalid {label}')
    number = Decimal(str(value))
    if (not number.is_finite() or number < 0 or number >= Decimal(10) ** (precision - scale)
            or number != number.quantize(Decimal(1).scaleb(-scale))):
        raise ValueError(f'Yuanhang {label} exceeds numeric contract')
    return number


def _validated(tables, code, start, end, fields):
    validate_history_tables(tables, security=security_identity(code), required_fields=set(fields),
                            start=day_number(start), end=day_number(end))
    for table in tables:
        if any(field & 0x80000000 for field, *_ in table['fields']):
            raise ValueError('Yuanhang returned an unsupported history field')


def _same_grid(tables, fields):
    """Join by date only when all required fields have identical date sets."""
    columns = {}
    for table in tables:
        for field, *_ in table['fields']:
            if field in fields - {1}:
                columns[field] = {row[1]: row[field] for row in table['rows']}
    grids = [set(values) for values in columns.values()]
    if not grids or any(grid != grids[0] for grid in grids[1:]):
        raise ValueError('Yuanhang required fields have different date sets')
    return [{1: day, **{field: values[day] for field, values in columns.items()}}
            for day in sorted(grids[0])]


@dataclass(frozen=True)
class DailyBar:
    unified_code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_shares: Decimal
    amount_yuan: Decimal


@dataclass(frozen=True)
class CorporateAction:
    unified_code: str
    ex_date: date
    bonus_ratio: Decimal
    transfer_ratio: Decimal
    rights_ratio: Decimal
    rights_price: Decimal
    cash_per_share: Decimal


@dataclass(frozen=True)
class CapitalPoint:
    unified_code: str
    effective_date: date
    kind: str
    shares: Decimal


def normalize_daily(tables, *, unified_code: str, start: date, end: date) -> tuple[DailyBar, ...]:
    _validated(tables, unified_code, start, end, DAILY_FIELDS)
    result = []
    for row in _same_grid(tables, DAILY_FIELDS):
        values = {field: _number(row[field], label=str(field)) for field in DAILY_FIELDS - {1}}
        if not (0 < values[9] <= min(values[7], values[11])
                <= max(values[7], values[11]) <= values[8]):
            raise ValueError('Yuanhang daily OHLC ordering or positive-price constraint failed')
        result.append(DailyBar(unified_code, _date(row[1]), values[7], values[8], values[9],
                               values[11], values[13], values[19]))
    return tuple(result)


def normalize_actions(tables, *, unified_code: str, start: date, end: date) -> tuple[CorporateAction, ...]:
    _validated(tables, unified_code, start, end, ACTION_FIELDS)
    result = []
    for row in _same_grid(tables, ACTION_FIELDS):
        values = {field: _number(row[field], label=str(field)) for field in ACTION_FIELDS - {1}}
        if values[454] < values[460]:
            raise ValueError('Yuanhang total bonus/transfer ratio is smaller than transfer ratio')
        if values[455] > 0 and values[456] <= 0:
            raise ValueError('Yuanhang rights issue lacks a positive subscription price')
        # 454 includes 460: adding both would apply the transfer twice.
        result.append(CorporateAction(unified_code, _date(row[1]), values[454] - values[460],
                                      values[460], values[455], values[456], values[463]))
    return tuple(result)


def normalize_capital(tables, *, unified_code: str, start: date, end: date,
                      fields: frozenset[int] = frozenset(CAPITAL_FIELDS)) -> tuple[CapitalPoint, ...]:
    if not fields or not fields <= CAPITAL_FIELDS.keys():
        raise ValueError('Yuanhang unverified capital field requested')
    _validated(tables, unified_code, start, end, fields | {1})
    result = []
    for table in tables:
        for row in table['rows']:
            for field in sorted(fields & row.keys()):
                shares = _number(row[field], label=str(field))
                if shares <= 0:
                    raise ValueError('Yuanhang capital balance must be positive')
                result.append(CapitalPoint(unified_code, _date(row[1]), CAPITAL_FIELDS[field], shares))
    return tuple(sorted(result, key=lambda point: (point.kind, point.effective_date)))


def history_query(*, unified_code: str, dataset: str, start: date, end: date,
                  instance: int) -> bytes:
    """Only verified unadjusted day/financial requests; no arbitrary wire injection."""
    security = security_identity(unified_code)
    first, last = day_number(start), day_number(end)
    if first > last or not 1 <= instance <= 2147483647 or type(instance) is not int:
        raise ValueError('Yuanhang invalid history request bounds or instance')
    if dataset == 'daily':
        request_id, fields = 210, DAILY_FIELDS
    elif dataset == 'actions':
        request_id, fields = 211, ACTION_FIELDS
    elif dataset == 'capital':
        request_id, fields = 211, frozenset(CAPITAL_FIELDS) | {1}
    else:
        raise ValueError('Yuanhang unknown history dataset')
    # Financial full-history requests use the source's verified 0/0 convention.
    # Bounds still apply during normalization; never silently truncate a reply.
    if request_id == 211:
        first = last = 0
    return (f'id={request_id}&market={security[:4]}&code={security[4:]}&start={first}&end={last}'
            f'&period=16384&datatype={",".join(map(str, sorted(fields)))}'
            f'&zipversion=2&instance={instance}').encode('ascii')
