"""Official archived inputs, same SQL snapshot, independent oracle and safe replay."""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from tests.integration import test_adjustment_pipeline as adjustment

inputs = adjustment.inputs
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Private UUID MySQL/Redis opt-in"
    ),
    pytest.mark.parametrize('inputs', [6.09], indirect=True),
]
SCOPE = dict(codes=["000001"], start="2026-09-01", end="2026-09-02")


async def dividend_query(q):
    from empire.features.capital_actions.query import CapitalDataPlugin

    query = CapitalDataPlugin("dividends", namespace=q.namespace)
    from types import SimpleNamespace

    await query.start(
        SimpleNamespace(
            get=lambda key: q.mysql,
            optional=lambda key: q.quotes if key == "kaipanla_quote.query" else None,
        )
    )
    # Explicit synthetic isolated input, not source or production coverage.
    from empire.plugins.infra.collection_state import save_state

    with q.mysql.engine.begin() as conn:
        save_state(conn, q.namespace, 'tdx-suspensions', 'tdx', 'suspensions.period', dict(
            collection_integrity_version=2, source_calendar_version=1, coverage={
                'from': '2004-12-27', 'through': '2026-09-30',
                'confirmed_at': datetime.now().astimezone().isoformat()}), {})
    return query


async def test_denominator_suspension_exact_day_and_full_source_identity(inputs):
    from empire.core.time import CHINA
    from empire.features.suspensions.query import closing_price_evidence
    from empire.plugins.infra.collection_state import read_state, save_state

    q, _, _, _, _, _, _ = inputs
    await dividend_query(q)
    day, now = date(2026, 9, 2), datetime.now(CHINA)
    def check():
        with q.mysql.read_engine.connect() as conn:
            return closing_price_evidence(conn, q.namespace, '000001.SZ', day, now)
    # An old null-resume record is retained, not extended to the denominator day.
    with q.mysql.engine.begin() as conn:
        conn.execute(text("INSERT INTO suspension_event "
            "(unified_code,suspended_at,resume_key,record_key,name,resumed_at,source_dates_known,"
            "suspension_type,source_note,reason,version_observed_at) VALUES "
            "('000001.SZ','2005-01-04 09:30','1000-01-01',:key,'样本',NULL,1,"
            "'full_day','停牌','历史未知',:now)"), dict(key='a'*64, now=now.replace(tzinfo=None)))
        # Same record_key on another date/security is not evidence for our row.
        conn.execute(text("INSERT INTO suspension_source_date VALUES "
            "(:day,'600000.SH','2005-01-04 09:30','1000-01-01',:key)"), dict(day=day, key='a'*64))
    assert check()['date'] == day.isoformat()
    with q.mysql.engine.begin() as conn:
        conn.execute(text("INSERT INTO suspension_source_date VALUES "
            "(:day,'000001.SZ','2005-01-04 09:30','1000-01-01',:key)"), dict(day=day, key='a'*64))
    with pytest.raises(ValueError, match='未裁定'):
        check()
    # An explicit resumption before this day's opening is not a current halt.
    with q.mysql.engine.begin() as conn:
        conn.execute(text("UPDATE suspension_event SET resumed_at='2026-09-02 09:30',resume_key='2026-09-02 09:30'"))
    assert check()['source'] == 'tdx'
    with q.mysql.engine.begin() as conn:
        conn.execute(text("UPDATE suspension_event SET resumed_at='2026-09-02 10:30',resume_key='2026-09-02 10:30'"))
    with pytest.raises(ValueError, match='停复牌'):
        check()
    with q.mysql.engine.begin() as conn:
        state = read_state(conn, q.namespace, 'tdx-suspensions', 'tdx')
        previous = {**state}
        state['coverage'] = {**state['coverage'], 'confirmed_at': '2026-09-02T14:00:00+08:00'}
        save_state(conn, q.namespace, 'tdx-suspensions', 'tdx', 'suspensions.period', state, previous)
    with pytest.raises(ValueError, match='覆盖未证明'):
        check()


async def test_readonly_yield_cache_revision_and_sql_only_evidence(inputs):
    q, store, quote, dividend, _, now, _ = inputs
    query = await dividend_query(q)
    await dividend(6.09)
    await quote("2026-09-01", 12)
    await quote("2026-09-02", 12)
    statements = []

    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(q.mysql.read_engine, "before_cursor_execute", capture)
    try:
        result = await query.dividend_yield(SCOPE)
        assert result["state"] == "已计算", result.get("problem")
        assert result["securities"][0]["yield_percent"] == "5.075"  # hand 609/120
        assert result["securities"][0]["denominator"]["date"] == "2026-09-02"
        assert sum(s.startswith("START TRANSACTION READ ONLY") for s in statements) == 1
        assert all(s.lstrip().split()[0].upper() in {"START", "SELECT"} for s in statements)
        before = result["input_hash"]
        await quote("2026-09-02", 10, now + timedelta(minutes=2))
        revised = await query.dividend_yield(SCOPE)
        assert revised["securities"][0]["yield_percent"] == "6.09"
        assert revised["input_hash"] != before
        await quote("2026-09-02", 12, now + timedelta(minutes=1))
        assert (await query.dividend_yield(SCOPE))["input_hash"] == revised["input_hash"]
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.read_engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("case", ["missing", "intraday", "basis", "bonus", "historical"])
async def test_yield_failure_does_not_invalidate_nominal_distribution(inputs, case):
    q, store, quote, dividend, _, now, _ = inputs
    query = await dividend_query(q)
    await dividend(6.09)
    if case != "missing":
        await quote(
            "2026-09-01", 12, now + timedelta(minutes=2), shares=900 if case == "basis" else 1000
        )
        await quote(
            "2026-09-02",
            12,
            now + timedelta(minutes=2),
            clock=140000000 if case == "intraday" else 153833000,
        )
    request = {**SCOPE, "purpose": "historical_signal"} if case == "historical" else (
        {**SCOPE, 'end':'2026-09-03'} if case == 'missing' else SCOPE)
    if case == "bonus":
        # Existing source fixture doesn't expose bonus mutation: require unknown
        # shares directly through the formal quote contract instead.
        await quote("2026-09-02", 12, now + timedelta(minutes=3), shares=None)
    blocked = await query.dividend_yield(request)
    assert blocked["state"] in ("数据阻断", "来源受限") and blocked["securities"] == []
    nominal = await query.distribution_summary(SCOPE)
    assert nominal["state"] == "已计算" and Decimal(
        nominal["securities"][0]["cash_per_share"]
    ) == Decimal("0.609")
    assert await store.client.xlen(store.stream) == 0
