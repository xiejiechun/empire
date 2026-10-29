"""Input proof boundaries and registration of computations, without fake collectors."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.contracts.preparation import ComputationContribution
from empire.features.adjustment.query import AdjustmentDataPlugin, resolve_security
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
        assert c.cache_revision == 3  # Old successful checks cannot bypass new ambiguity rejection.
        checks = prep.development(c, {}, '尚未运行测试', '计算')
        assert all(x['status'] == 'pass' for x in checks[:3])
        assert all(x['status'] == 'unknown' for x in checks[3:5])
    assert not any('adjustment' in dataset for dataset in manager.entries['dataset.astock'].plugin.datasets)


async def test_preparation_missing_scope_does_not_scan_all_history():
    q = AdjustmentDataPlugin()
    q.mysql = SimpleNamespace(read=AsyncMock())
    checks = await q.preparation_check()
    assert all(c.status == 'unknown' for c in checks)
    q.mysql.read.assert_not_called()




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
