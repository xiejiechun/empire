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


class IncompleteFinancialHistory(ValueError):
    """Validated single total/circulating point; absence needs listing evidence."""

    def __init__(self):
        super().__init__('Yuanhang free-float field omitted from validated partial capital history')


def price_quality(op, high, low, close):
    """Derived source-quality bit 1; preserve reported values without repair."""
    return int(not (low <= min(op, close) <= max(op, close) <= high))


def security_identity(unified_code: str, native_market: str | None = None) -> str:
    if not isinstance(unified_code, str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', unified_code):
        raise ValueError('Yuanhang requires a unified SH/SZ/BJ security code')
    code, market = unified_code.split('.')
    permitted = ('USHA', 'USHT') if market == 'SH' else (MARKETS[market],)
    native_market = native_market or MARKETS[market]
    if native_market not in permitted:
        raise ValueError('Yuanhang native market does not match unified security')
    return native_market + code


def day_number(value: date) -> int:
    if type(value) is not date:
        raise ValueError('Yuanhang history boundary must be a date')
    return value.year * 10000 + value.month * 100 + value.day


def _date(value: int) -> date:
    return date(value // 10000, value // 100 % 100, value % 100)


def _number(value, *, label: str, precision: int = 28, scale: int = 10, signed=False) -> Decimal:
    # str(float) preserves the decoded binary64's shortest round-trip decimal.
    # Never round values to fit SQL: an unexplained extra digit needs investigation.
    if type(value) not in (int, float, Decimal):
        raise ValueError(f'Yuanhang missing or invalid {label}')
    number = Decimal(str(value))
    if (not number.is_finite() or (number <= -1 if signed else number < 0)
            or number >= Decimal(10) ** (precision - scale)
            or number != number.quantize(Decimal(1).scaleb(-scale))):
        raise ValueError(f'Yuanhang {label} exceeds numeric contract')
    return number


def _validated(tables, code, start, end, fields, native_market=None, *, financial=False):
    validate_history_tables(tables, security=security_identity(code, native_market), required_fields=set(fields),
                            start=day_number(start), end=day_number(end),
                            repeatable_fields=ACTION_FIELDS if financial else frozenset(),
                            identical_fields=DAILY_FIELDS if fields == DAILY_FIELDS and not financial else frozenset())
    for table in tables:
        if any(field & 0x80000000 for field, *_ in table['fields']):
            raise ValueError('Yuanhang returned an unsupported history field')


def _same_grid(tables, fields):
    """Join by date only when all required fields have identical date sets."""
    # Only complete daily tables can contain previously validated exact repeats.
    # Conflicting same-day values and repeats in partial grids are rejected first.
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
    volume_shares: Decimal | None
    amount_yuan: Decimal | None


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
    shares: Decimal | None


@dataclass(frozen=True)
class FinancialHistory:
    actions: tuple[CorporateAction, ...]
    capital: tuple[CapitalPoint, ...]


def normalize_daily(tables, *, unified_code: str, start: date, end: date,
                    native_market: str | None = None) -> tuple[DailyBar, ...]:
    _validated(tables, unified_code, start, end, DAILY_FIELDS, native_market)
    result = []
    for row in _same_grid(tables, DAILY_FIELDS):
        values = {field: _number(row[field], label=str(field)) for field in DAILY_FIELDS - {1, 13, 19}}
        # Observed native missing-value sentinel on 2005-01-05 for SH stocks.
        # Preserve the source absence; it is neither zero nor a missing day.
        amount = None if row[19] is None else _number(row[19], label='19')
        volume = None if row[13] is None else _number(row[13], label='13')
        if any(values[f] <= 0 for f in (7, 8, 9, 11)):
            raise ValueError(f'Yuanhang daily nonpositive price: {unified_code}/{row[1]}')
        result.append(DailyBar(unified_code, _date(row[1]), values[7], values[8], values[9],
                               values[11], volume, amount))
    return tuple(result)


def normalize_actions(tables, *, unified_code: str, start: date, end: date,
                      native_market: str | None = None) -> tuple[CorporateAction, ...]:
    _validated(tables, unified_code, start, end, ACTION_FIELDS, native_market, financial=True)
    result = []
    complete = [t for t in tables if {f for f, *_ in t['fields']} == ACTION_FIELDS]
    rows = complete[0]['rows'] if complete else _same_grid(tables, ACTION_FIELDS)
    for row in rows:
        values = {field: _number(row[field], label=str(field), signed=field == 454) for field in ACTION_FIELDS - {1}}
        if values[454] < 0 and any(values[f] != 0 for f in (455, 456, 460, 463)):
            raise ValueError('Yuanhang negative share ratio requires a pure consolidation event')
        if values[454] >= 0 and values[454] < values[460]:
            raise ValueError('Yuanhang total bonus/transfer ratio is smaller than transfer ratio')
        if values[455] > 0 and values[456] <= 0:
            raise ValueError('Yuanhang rights issue lacks a positive subscription price')
        # 454 includes 460: adding both would apply the transfer twice.
        result.append(CorporateAction(unified_code, _date(row[1]), values[454] - values[460],
                                      values[460], values[455], values[456], values[463]))
    return tuple(result)


def normalize_capital(tables, *, unified_code: str, start: date, end: date,
                      fields: frozenset[int] = frozenset(CAPITAL_FIELDS),
                      native_market: str | None = None) -> tuple[CapitalPoint, ...]:
    if not fields or not fields <= CAPITAL_FIELDS.keys():
        raise ValueError('Yuanhang unverified capital field requested')
    _validated(tables, unified_code, start, end, fields | {1}, native_market, financial=True)
    result = []
    for table in tables:
        for row in table['rows']:
            for field in sorted(fields & row.keys()):
                shares = None if field == 407 and row[field] is None else _number(row[field], label=str(field))
                if shares is not None and shares <= 0:
                    raise ValueError('Yuanhang capital balance must be positive')
                result.append(CapitalPoint(unified_code, _date(row[1]), CAPITAL_FIELDS[field], shares))
    return tuple(sorted(result, key=lambda point: (point.kind, point.effective_date)))


def normalize_financial(tables, *, unified_code: str, start: date, end: date,
                        native_market: str | None = None) -> FinancialHistory:
    """One complete 211 response: sparse capital and optional whole action series.

    A no-table envelope is never valid. All three capital series must positively
    identify the requested security. Missing *all* action columns means no source
    action series; a partial series, unsupported field or null is an error.
    """
    # Observed prelisting shape (688827.SH): exactly one dated total/circulating
    # point (407 may explicitly be NULL), no actions and no free-float.
    # Validate identity, extent and all available values
    # before exposing this specific condition; arbitrary missing fields fail.
    if (len(tables) == 1 and len(tables[0]['rows']) == 1
            and {f for f, *_ in tables[0]['fields']} == {1, 402, 407}):
        _validated(tables, unified_code, start, end, {1, 402, 407}, native_market)
        row = tables[0]['rows'][0]
        if _number(row[402], label='402') <= 0:
            raise ValueError('Yuanhang partial total capital must be positive')
        if row[407] is not None and _number(row[407], label='407') <= 0:
            raise ValueError('Yuanhang partial circulating capital must be positive or explicitly absent')
        raise IncompleteFinancialHistory()
    capital = normalize_capital(tables, unified_code=unified_code, start=start, end=end,
                                native_market=native_market)
    present = {field for table in tables for field, *_ in table['fields']}
    allowed = ACTION_FIELDS | CAPITAL_FIELDS.keys()
    if present - allowed:
        raise ValueError('Yuanhang unexpected financial fields')
    action_columns = present & (ACTION_FIELDS - {1})
    if action_columns and action_columns != ACTION_FIELDS - {1}:
        raise ValueError('Yuanhang partial corporate action series')
    actions = (normalize_actions(tables, unified_code=unified_code, start=start, end=end,
                                 native_market=native_market)
               if action_columns else ())
    return FinancialHistory(actions, capital)


def history_query(*, unified_code: str, dataset: str, start: date, end: date,
                  instance: int, native_market: str | None = None) -> bytes:
    """Only verified unadjusted day/financial requests; no arbitrary wire injection."""
    security = security_identity(unified_code, native_market)
    first, last = day_number(start), day_number(end)
    if first > last or not 1 <= instance <= 2147483647 or type(instance) is not int:
        raise ValueError('Yuanhang invalid history request bounds or instance')
    if dataset == 'daily':
        request_id, fields = 210, DAILY_FIELDS
    elif dataset == 'financial':
        request_id, fields = 211, ACTION_FIELDS | CAPITAL_FIELDS.keys()
    else:
        raise ValueError('Yuanhang unknown history dataset')
    # Financial full-history requests use the source's verified 0/0 convention.
    # Bounds still apply during normalization; never silently truncate a reply.
    if request_id == 211:
        first = last = 0
    return (f'id={request_id}&market={security[:4]}&code={security[4:]}&start={first}&end={last}'
            f'&period=16384&datatype={",".join(map(str, sorted(fields)))}'
            f'&zipversion=2&instance={instance}').encode('ascii')
