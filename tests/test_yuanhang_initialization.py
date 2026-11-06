from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang.availability import DeferredSecurity
from empire.sources.yuanhang_payload import digest
from scripts.initialize_yuanhang_history import audit, source_proofs, summarize
from scripts.yuanhang_initialization_audit import require_owned_pending, seed
from tests.test_yuanhang_payload import CODE, bar, snapshot


def test_source_summary_preserves_full_scope_and_empty_intermediate_year():
    proof = source_proofs(snapshot((bar('2020-10-19'), bar('2022-01-04'))), CODE, '2023-12-31', False)
    assert set(proof) == {2020, 2021, 2022, 2023}
    item = summarize(CODE, proof)
    assert item['rows'] == 2 and item['units'] == 4
    assert item['first'] == '2020-10-19' and item['last'] == '2022-01-04'


async def test_actual_annual_key_set_and_source_content_failures_are_reported():
    query = SimpleNamespace(audit_source_proofs=AsyncMock(return_value=['2020:content']),
                            price_quality=AsyncMock(return_value={'ohlc_anomalies': 0}),
                            year_heads=AsyncMock(return_value={2020:{}, 2021:{}}))
    expected = {CODE: source_proofs(snapshot((bar('2020-10-19'),)), CODE, '2020-12-31', False)}
    result = await audit(query, [CODE], expected, financial=False)
    assert result[0]['problems'] == ['2020:content', 'annual_key_set_mismatch']
    assert expected == {}


async def test_same_count_different_source_security_set_cannot_pass():
    with pytest.raises(ValueError, match='证券集合'):
        await audit(None, [CODE], {'000001.SZ': {}}, financial=False)


@pytest.mark.parametrize('financial', [False, True])
@pytest.mark.parametrize('exists', [False, True])
async def test_prelisting_scope_proof_is_distinct_from_zero_business_rows(financial, exists):
    snapshot = DeferredSecurity(CODE, None, '2026-10-23')
    q = SimpleNamespace(has_history=AsyncMock(return_value=exists), audit_source_proofs=AsyncMock())
    expected = {CODE: source_proofs(snapshot, CODE, '2026-10-23', financial)}
    result = await audit(q, [CODE], expected, financial=financial)
    assert result[0]['status'] == 'deferred_prelisting'
    assert result[0]['problems'] == (['prelisting_history_conflict'] if exists else [])
    q.audit_source_proofs.assert_not_awaited()


async def test_initial_capital_source_gap_cannot_certify_initialization():
    snapshot = DeferredSecurity(CODE, '2026-11-06', '2026-11-06', 'partial_total_circulating',
                                'deferred_initial_capital', '2026-11-06', 'node-test')
    query = SimpleNamespace(has_history=AsyncMock(return_value=False), audit_source_proofs=AsyncMock())
    result = await audit(query, [CODE], {CODE: source_proofs(snapshot, CODE, '2026-11-06', True)}, financial=True)
    assert result[0]['problems'] == ['initial_capital_source_gap']
    query.audit_source_proofs.assert_not_awaited()


@pytest.mark.parametrize('change', [None, 'target', 'through', 'prefix', 'unknown'])
def test_audit_continuation_requires_same_target_scope_and_exact_published_prefix(change):
    codes = [CODE, '000001.SZ']
    cursor = dict(next_index=1, scope_hash=digest(codes), through='2026-10-23', batch_id='batch')
    saved = dict(checkpoint=dict(revision=1,cursor=cursor), proofs={CODE:{'2020':{'contract_version':3}}})
    report = dict(target={'database':'test'},stocks=codes,scope_hash=digest(codes),through='2026-10-23',
                  audit_sources={'ths-yuanhang-prices':saved})
    if change == 'target':
        report['target'] = {'database':'other'}
    if change == 'through':
        report['through'] = '2026-10-22'
    if change == 'prefix':
        saved['proofs'] = {'000001.SZ':{}}
    if change == 'unknown':
        report['audit_sources'] = {'unknown':saved}
    if change:
        with pytest.raises(ValueError):
            seed(report,target={'database':'test'},codes=codes,through='2026-10-23')
    else:
        result=seed(report,target={'database':'test'},codes=codes,through='2026-10-23')
        assert set(result['ths-yuanhang-prices']['proofs'][CODE]) == {2020}


async def test_audit_continuation_rejects_unrelated_pending_without_deleting():
    from tests.test_yuanhang_storage import envelope
    e=envelope()
    client=SimpleNamespace(xrange=AsyncMock(return_value=[('1-0',{'envelope':e.model_dump_json()})]))
    store=SimpleNamespace(client=client,stream='owned')
    with pytest.raises(ValueError,match='不属于'):
        await require_owned_pending(store,{'ths-yuanhang-prices':{'checkpoint':{'cursor':{'batch_id':'other'}}}})
    assert client.xrange.await_count == 1
