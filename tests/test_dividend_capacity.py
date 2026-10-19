"""Full capacity counterexamples, plus opt-in actual guarded SQL seeding."""
import copy
import importlib
import os
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('dividend_capacity')


def test_same_count_different_keys_or_content_is_not_pipeline_equality(capacity):
    old = [dict(record_key='old', value=1)]
    current = [dict(record_key='new', value=2)]
    for actual in ([dict(record_key='other', value=2), *old],
                   [dict(record_key='new', value=3), *old], current):
        with pytest.raises(ValueError, match='集合或内容'):
            capacity.compare_history(old, current, actual)


def test_retained_history_is_reported_and_revisions_replace_same_identity(capacity):
    old = [dict(record_key='old', value=1), dict(record_key='changed', value=1)]
    current = [dict(record_key='changed', value=2), dict(record_key='new', value=3)]
    result = capacity.compare_history(old, current, [old[0], *current])
    assert result['retained_history_count'] == 1
    assert result['retained_history_keys'] == ['old']
    assert result['stored'] == 3 and result['current'] == 2
    with pytest.raises(ValueError, match='重复'):
        capacity.compare_history(old, current, [old[0], *current, current[0]])


@pytest.mark.parametrize('metric', ['source_rows', 'planned_periods', 'payload_bytes',
                                   'maximum_payload_bytes', 'query_p95_upper_ms'])
def test_each_original_budget_is_enforced(capacity, metric):
    measured = dict(capacity.LIMITS)
    assert capacity.capacity_checks(measured)
    measured[metric] += 1
    with pytest.raises(ValueError, match='冻结阈值'):
        capacity.capacity_checks(measured)


def test_no_partial_or_nonfinite_capacity_is_accepted(capacity):
    with pytest.raises(ValueError, match='缺少'):
        capacity.capacity_checks(dict(payload_bytes=1))
    for value in (0, float('nan'), float('inf'), True):
        measured = dict(capacity.LIMITS, planned_periods=value)
        with pytest.raises(ValueError):
            capacity.capacity_checks(measured)


async def test_observation_preserves_deferred_ownership(capacity):
    from empire.plugins.collection.unit_prefetch import DeferredResponse
    consume = AsyncMock(return_value=([dict(record_key='a')], datetime.now(UTC)))
    response = DeferredResponse(SimpleNamespace(close=lambda: None), consume)
    observed = []
    original = AsyncMock(return_value=response)
    wrapper = capacity.observe_fetch(original, lambda args, result: observed.append((args, result)))
    result = await wrapper('collector', 'dividends', '2025-12-31', defer=True)
    assert result is response and not observed and consume.await_count == 0
    resolved = await result.consume()
    assert observed[0][1] == resolved and consume.await_count == 1


async def test_failure_restores_all_observers(capacity, monkeypatch):
    collector = SimpleNamespace(job_key='tdx-dividends-v1', ingest=SimpleNamespace(publish_page=AsyncMock()),
                                execute=AsyncMock(side_effect=ValueError('source failure')))
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=lambda key:
        collector if key.startswith('collector.') else object()))
    before = (capacity.dividend_history.report_periods, capacity.source.complete_response,
              capacity.dividend_history.collect_history, collector.ingest.publish_page)
    with pytest.raises(ValueError, match='source failure'):
        await capacity.verify_scope(manager, {}, SimpleNamespace(proxy_only=True), dict(results={}))
    after = (capacity.dividend_history.report_periods, capacity.source.complete_response,
             capacity.dividend_history.collect_history, collector.ingest.publish_page)
    assert before == after


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL opt-in')
async def test_actual_owned_seed_and_formal_query(capacity, monkeypatch):
    import json
    from secrets import token_hex
    from uuid import uuid4

    from source_test_storage import PrivateStorage, read_server_uuid
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from empire.features.capital_actions.contract import digest
    from empire.features.capital_actions.parser import parse
    from empire.plugins.infra.mysql_store import make_engine
    from tests.capital_samples import source
    from tests.prefetch_source import prefetch_http

    cfg = load_config()
    settings = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = PrivateStorage(settings, cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager = None
    report = dict(cleanup={}, errors=[])
    row = parse('dividends', source('dividends'), 10000, '2025-12-31')[0][0]
    snapshot = dict(rows=[dict(unified_code='688110.SH', record_key=row['record_key'], name=row['name'],
        market='SH', code='688110', event_date=date.fromisoformat(row['event_date']),
        payload=row['data'], content_hash=digest(row),
        version_observed_at=datetime(2026, 1, 1))], state=dict(source='tdx', dataset='dividends',
        payload=dict(contract_version=3, units={'SH:688110': dict(count=1, digest=digest([row]),
            observed_at='2026-01-01T00:00:00+00:00', history_discovered_at='2026-01-01T00:00:00+00:00')}),
        updated_at=datetime(2026, 1, 1)))
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([dict(unified_code='688110.SH', name=row['name'])], [])
        capacity.seed_history(storage, snapshot)
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'], test_cfg['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(test_cfg)
        await manager.start('data.dividends')
        query = manager.registry.get('dividends.query')
        assert await query.list_events(code='688110', limit=51) == [row]
        assert await query.dividend_report_dates() == ['2025-12-31']
        # Synthetic source through actual observer->Redis->archiver->query. This
        # tests the tool; it is deliberately not real-source capacity evidence.
        import httpx
        await manager.start('collector.tdx_dividends')
        collector = manager.registry.get('collector.tdx_dividends')
        collector.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200,
            json=source('dividends'))), response_policy=lambda profile: profile)
        monkeypatch.setattr(capacity.dividend_history, 'report_periods',
                            AsyncMock(return_value=['2025-12-31']))
        observed = dict(results={})
        await capacity.verify_scope(manager, snapshot, SimpleNamespace(proxy_only=False), observed)
        result = observed['results']['dividends']
        assert result['pipeline_verified'] and result['acceptance_complete'] and result['pending'] == 0
        assert result['measured']['source_rows'] == result['measured']['planned_periods'] == 1
        assert len(result['query_timings_ms']) == 10 and result['comparison']['retained_history_count'] == 0
        assert not result['strict_proxy_verified'] and not result['sample_30_claimed']
        # Actual private-session guard remains installed for seeded and query SQL.
        engine = make_engine(storage.settings)
        try:
            with engine.connect() as conn:
                with pytest.raises(ValueError, match='跨库'):
                    conn.exec_driver_sql('SELECT * FROM mysql.user')
        finally:
            engine.dispose()
    finally:
        await finish(manager, storage, None, report, Redactor([storage.owner]))
    assert not report['errors'] and all(report['cleanup'].values()) and report['remaining'] == dict(sql=False, redis=False)
