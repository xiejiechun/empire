"""Source observers preserve ownership; real SQL uses the shared private guards."""
import asyncio
import copy
import importlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('verify_ths_capital')


def test_exact_sql_authority_order_and_fields(verifier):
    from empire.contracts.business_schema import dataset_tables
    from empire.features.ths_capital.contract import DATASET, SPECS, TABLES
    assert TABLES == dataset_tables(DATASET) == tuple(SPECS)


def test_random_thirty_and_known_failures_are_retained(verifier):
    pool = [dict(unified_code=f'{600000+i:06d}.SH', name='sample') for i in range(100)]
    a = verifier.verification.select_stocks(pool, 30, 20261020, ['600001.SH', '600002.SH'])
    assert len(set(a['random'])) == 30
    assert {'600001.SH', '600002.SH'} <= {s['unified_code'] for s in a['selected']}
    assert verifier.verification.select_stocks(list(reversed(pool)), 30, 20261020, ['600001.SH', '600002.SH']) == a
    assert '000513.SZ' in verifier.FIXED_CODES and '601969.SH' in verifier.FIXED_CODES


async def test_deferred_observer_preserves_response_and_waits_for_consumption(verifier):
    from empire.plugins.collection.unit_prefetch import DeferredResponse
    from tests.test_ths_capital import STOCK, source
    value = verifier.verification.digest
    parsed = importlib.import_module('empire.features.ths_capital.source').parse(source().encode('gb18030'), STOCK)
    response = SimpleNamespace(close=AsyncMock())
    consume = AsyncMock(return_value=(parsed, datetime.now(UTC), 'https://example.invalid/'))
    original_result = DeferredResponse(response, consume)
    expected = {}
    wrapped = verifier.observe_fetch(AsyncMock(return_value=original_result), expected)
    result = await wrapped(STOCK, defer=True)
    assert result is original_result and result.response is response and not expected
    returned = await result.consume()
    assert value(expected[STOCK['unified_code']]['value']) == value(parsed) and returned[0] == parsed
    consume.assert_awaited_once()
    assert not response.close.called


async def test_same_count_different_set_rejected_before_redis_commit(verifier):
    from empire.contracts.data import make_envelope
    from empire.features.ths_capital.source import parse
    from empire.features.ths_capital.transport import SCHEMA, pack
    from tests.test_ths_capital import STOCK, source
    original = parse(source().encode('gb18030'), STOCK)
    wrong = copy.deepcopy(original)
    wrong['rows']['capital_project'][0]['project_name'] = 'different subject'
    e = make_envelope(source='ths', dataset=verifier.DATASET, schema_version=SCHEMA, job_key=verifier.JOB,
        run_id=uuid4().hex, batch_id=uuid4().hex,
        business_key=STOCK['unified_code'], payload=dict(page=1, unit=STOCK['unified_code'],
        rows=pack(wrong['rows']), availability=wrong['availability'], manifest=None))
    commit = AsyncMock()
    wrapped = verifier.observe_publish(commit, {STOCK['unified_code']: dict(value=original)}, [])
    with pytest.raises(ValueError, match='正式入队集合'):
        await wrapped([e], expected_revision=0)
    commit.assert_not_awaited()


async def test_cancel_restores_observers_and_routing(verifier):
    ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})), publish_page=AsyncMock())
    collector = SimpleNamespace(ingest=ingest, fetch=AsyncMock(), execute=AsyncMock(side_effect=asyncio.CancelledError()))
    resources = {'collector.ths_capital': collector, 'ths_capital.query': object()}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    before = collector.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get()
    with pytest.raises(asyncio.CancelledError):
        await verifier.verify_scope(manager, dict(selected=[]), SimpleNamespace(proxy_only=False), dict(results={}))
    assert before == (collector.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get())


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL/Redis opt-in')
async def test_actual_guarded_nine_sections_and_public_queries(verifier):
    import httpx
    from source_test_storage import PrivateStorage, read_server_uuid
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.prefetch_source import prefetch_http
    from tests.test_ths_capital import STOCK, source

    cfg = load_config()
    test = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = PrivateStorage(test, cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager, cleanup = None, dict(cleanup={}, errors=[])
    stocks = [STOCK, dict(code='600000', unified_code='600000.SH', name='合成样本')]
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed(stocks, [])
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'], test_cfg['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(test_cfg)
        await manager.start('pipeline.archive')
        await manager.start('collector.ths_capital')
        collector = manager.registry.get('collector.ths_capital')
        collector.session = SimpleNamespace(headers=lambda url: {})
        def response(method, url, **kwargs):
            body = source().replace('value="601139"', 'value="' + url.split('/')[-2] + '"')
            return httpx.Response(200, content=body.encode('gb18030'))
        collector.http = prefetch_http(request=AsyncMock(side_effect=response))
        report = dict(results={})
        await verifier.verify_scope(manager, dict(selected=stocks), SimpleNamespace(proxy_only=False), report)
        result = report['results']['ths_capital']
        assert result['pipeline_verified'] and result['acceptance_complete'] and result['pending'] == 0
        assert not result['strict_proxy_verified']
        assert set(result['query_units']) == {s['unified_code'] for s in stocks}
        assert all(len(r) == 8 for r in result['query_units'].values())
        assert set(result['preparation']) == set(verifier.SECTIONS)
    finally:
        await finish(manager, storage, None, cleanup, Redactor([storage.owner]))
    assert not cleanup['errors'] and all(cleanup['cleanup'].values())
