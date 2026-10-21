"""Input proof boundaries and registration of computations, without fake collectors."""
from concurrent.futures import Future
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PySide6.QtWidgets import QApplication

from empire.bootstrap import build_manager
from empire.contracts.preparation import ComputationContribution
from empire.features.adjustment.inputs import close_prices, proof_time, verify_unit
from empire.features.adjustment.query import AdjustmentDataPlugin, resolve_security
from empire.features.adjustment.ui import AdjustmentPage
from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.event_rules import ActionError
from empire.features.preparation.catalog import BY_ID


def test_auto_market_resolves_catalogue_and_manual_mismatch_explains_correct_market():
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(scalars=lambda: ['600009.SH']))
    assert resolve_security(conn, 'AUTO', '600009') == '600009.SH'
    assert resolve_security(conn, 'SH', '600009') == '600009.SH'
    with pytest.raises(ActionError, match='属于SH市场'):
        resolve_security(conn, 'SZ', '600009')
    missing = SimpleNamespace(execute=lambda *args: SimpleNamespace(scalars=lambda: []))
    with pytest.raises(ActionError, match='不存在或市场不唯一'):
        resolve_security(missing, 'AUTO', '000001')
    assert resolve_security(missing, 'SZ', '000001') == '000001.SZ'


def test_calculation_registration_is_not_a_collector_or_archive():
    cfg = dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={})
    manager = build_manager(cfg)
    q = manager.entries['data.adjustment'].plugin
    prep = manager.entries['data.preparation'].plugin
    assert all(isinstance(c, ComputationContribution) for c in q.preparation)
    assert BY_ID['adjustment_factors'].kind == '计算'
    assert 'security_types' not in BY_ID
    assert 'adjustment' not in manager.entries['collection.control'].plugin.definitions
    for c in q.preparation:
        assert c.cache_revision == 2  # Old successful checks cannot bypass new ambiguity rejection.
        checks = prep.development(c, {}, '尚未运行测试', '计算')
        assert all(x['status'] == 'pass' for x in checks[:3])
        assert all(x['status'] == 'unknown' for x in checks[3:5])
    assert not any('adjustment' in dataset for dataset in manager.entries['dataset.astock'].plugin.datasets)


def test_complete_empty_input_requires_proof_and_same_count_different_set_fails():
    state = dict(contract_version=3, units={'SZ:000001': dict(count=0, digest=digest([]),
                                                           observed_at=datetime.now(UTC).isoformat())})
    assert verify_unit('dividends', 'SZ:000001', [], state)
    state['units']['SZ:000001']['digest'] = digest(['not-the-empty-set'])
    with pytest.raises(ActionError, match='同数异集'):
        verify_unit('dividends', 'SZ:000001', [], state)
    with pytest.raises(ActionError):
        verify_unit('dividends', 'SZ:000001', [], {})


@pytest.mark.parametrize('value', [None, 'invalid', '2026-09-01T00:00:00', (datetime.now(UTC)+timedelta(days=1)).isoformat()])
def test_future_or_unzoned_proof_rejected(value):
    with pytest.raises(ActionError):
        proof_time(value)


def test_intraday_latest_quote_is_not_accepted_as_close():
    row = dict(trade_date='2026-09-01', lifecycle={'listing_date': '1991-01-01'},
               data=dict(real=dict(time=145900000, open_px=10, high_px=10, low_px=10, last_px=10)))
    query = SimpleNamespace(iter_validated_days=lambda *args: iter([row]))
    with pytest.raises(ActionError, match='收盘后'):
        close_prices(None, query, 'SZ', '000001', date(2026, 9, 1), date(2026, 9, 1))


@pytest.mark.parametrize('clock', [150000000, 150300870, 153759000])
def test_historical_close_clock_is_distinct_from_today_query_cutoff(clock, monkeypatch):
    day = date(2021, 1, 4)
    row = dict(trade_date=day.isoformat(), lifecycle={'listing_date': '1991-01-01'},
               data=dict(real=dict(time=clock, open_px=5.21, high_px=5.22, low_px=5.16, last_px=5.2)))
    query = SimpleNamespace(iter_validated_days=lambda *args: iter([row]))
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [dict(trade_date=day, is_trade=1)]))
    conn = SimpleNamespace(execute=lambda *args: result)
    monkeypatch.setattr('empire.features.adjustment.inputs.suspended', lambda *args: set())
    assert close_prices(conn, query, 'SH', '600016', day, day)[0]['close'] == '5.2'


async def test_preparation_missing_scope_does_not_scan_all_history():
    q = AdjustmentDataPlugin()
    q.mysql = SimpleNamespace(read=AsyncMock())
    checks = await q.preparation_check()
    assert all(c.status == 'unknown' for c in checks)
    q.mysql.read.assert_not_called()


def test_factor_page_has_independent_draft_and_discards_stale_query():
    app = QApplication.instance() or QApplication([])
    pending = Future()
    runtime = SimpleNamespace(invoke=lambda *a: pending)
    page = AdjustmentPage(SimpleNamespace(runtime=runtime, cfg={}))
    try:
        page.find()
        original = page.save_ui_state()
        page.code.setText('000001')
        pending.set_result({'rows': []})
        page.tick()
        assert page.result is None and '条件已改变' in page.status.text()
        page.restore_ui_state(original)
        assert page.code.text() == original['code']
        page.scope.close()
        assert page.scope.closed
    finally:
        page.timer.stop()
        page.deleteLater()
        app.processEvents()


async def test_computation_readiness_does_not_claim_source_version_history():
    q = AdjustmentDataPlugin()
    q.mysql = SimpleNamespace(read=AsyncMock(return_value=['000001.SZ']))
    q.calculate = AsyncMock(return_value=dict(rows=[{}], observed_at=datetime.now(UTC).isoformat()))
    scope = dict(codes=['000001'], start='2026-09-01', end='2026-09-02', purpose='historical_signal')
    checks = await q.preparation_check(scope)
    assert all(c.status == 'pass' for c in checks[:-1])
    assert checks[-1].status == 'fail'
    q.calculate.side_effect = ActionError('缺收盘', day='2026-09-01')
    checks = await q.preparation_check(scope)
    assert all(c.status == 'fail' for c in checks) and checks[0].findings[0]['date'] == '2026-09-01'
