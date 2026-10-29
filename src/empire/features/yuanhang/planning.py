"""Pure daily request planning from explicit coverage and the formal calendar."""
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256

from empire.sources.yuanhang_history import security_identity


@dataclass(frozen=True)
class DailyPlan:
    code: str
    mode: str
    start: str | None
    end: str
    native_market: str | None
    reason: str

    @property
    def requests(self):
        return int(self.start is not None)


def calendar_dates(days, through):
    """Require a contiguous calendar, including source-declared non-trading days."""
    if not days or len(days) > 150 * 366:
        raise ValueError('Planning calendar missing or exceeds limit')
    trade_days, previous = [], None
    for day, is_trade in days:
        parsed = date.fromisoformat(day)
        if (parsed.isoformat() != day or type(is_trade) is not int or is_trade not in (0, 1)
                or (previous is not None and parsed != previous + timedelta(days=1))):
            raise ValueError('Planning calendar incomplete or malformed')
        if is_trade and day <= through:
            trade_days.append(day)
        previous = parsed
    if not trade_days or trade_days[-1] != through or days[-1][0] < through:
        raise ValueError('Planning cutoff is not a verified trading day')
    return trade_days


def plan_daily(code, *, through, calendar, coverage=None, full_checked=None,
               latest_quote=None, native_market=None, gaps=(), lookback=5,
               audit_period=20, force=False):
    """One request per security: full audit replaces, rather than adds to, tail work.

    calendar supplies at least audit_period trading days before full_checked and
    lookback before coverage. If durable proof lies outside that bounded calendar,
    a full recheck is explicit in the reason, never a silent full-pool fallback.
    gaps contains already established missing/untrusted date ranges, not dates
    inferred from exchange openings without individual-security evidence.
    """
    security_identity(code, native_market)
    if type(lookback) is not int or not 1 <= lookback <= 60:
        raise ValueError('Lookback must be 1..60 trading days')
    if type(audit_period) is not int or not 1 <= audit_period <= 250:
        raise ValueError('Audit period must be 1..250 trading days')
    trades = calendar_dates(calendar, through)
    def full(reason):
        return DailyPlan(code, 'full', '1900-01-01', through, native_market, reason)
    if force:
        return full('explicit_full_verification')
    if coverage is None:
        return full('missing_initial_coverage')
    for value in (coverage, full_checked, latest_quote):
        if value is not None and (date.fromisoformat(value).isoformat() != value or value > through):
            raise ValueError('Invalid or future coverage evidence')
    if full_checked is None:
        return full('missing_full_verification')
    # Rank against the supplied complete calendar, using actual trading days.
    # SQL must supply the same fixed calendar origin for every invocation.
    bucket = int.from_bytes(sha256(code.encode('ascii')).digest()[:8], 'big') % audit_period
    due = next((d for i, d in reversed(list(enumerate(trades))) if i % audit_period == bucket), None)
    if due is not None and full_checked < due:
        return full('historical_audit_due')
    bounds = []
    for first, last in gaps:
        if date.fromisoformat(first).isoformat() != first or date.fromisoformat(last).isoformat() != last:
            raise ValueError('Invalid gap bounds')
        if first > last or last > through:
            raise ValueError('Gap outside requested horizon')
        bounds.append(first)
    if coverage < through:
        before = [d for d in trades if d <= coverage]
        if len(before) < lookback:
            return full('coverage_outside_planning_calendar')
        bounds.append(before[-lookback])
    if not bounds:
        return DailyPlan(code, 'skip', None, through, native_market, 'cutoff_already_verified')
    if latest_quote is None:
        return full('missing_nonempty_anchor')
    # Include a known traded date, so suspension does not require interpreting
    # identity-free zero-block replies as verified absence.
    start = min(*bounds, latest_quote)
    return DailyPlan(code, 'range', start, through, native_market,
                     'repair_and_tail' if gaps else 'tail_with_overlap')
