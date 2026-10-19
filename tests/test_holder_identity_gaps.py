"""An unidentified bond is a source gap, never another bond's identity."""
import copy
import json

import httpx
import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.data import make_envelope
from empire.features.holders.audit import unit_gaps
from empire.features.holders.contract import KINDS, validate_gaps
from empire.features.holders.source import parse
from scripts.holder_pending_schema import convert
from tests.test_ths_holders import STOCK, configured, source


def mixed_bonds():
    body = source()
    start = body.index('<div class="bd"><div class="sec">')
    block = body[start:body.rindex('</div></html>')]
    blank = block.replace('燃23转债', '').replace('bondholder_1', 'unknown_1')
    return body[:start] + blank + body[start:]


def test_unnamed_report_isolated_without_merging_named_same_period():
    gaps = []
    rows = parse(mixed_bonds(), 'bond_holders', STOCK, gaps=gaps)
    assert rows == parse(source(), 'bond_holders', STOCK)
    assert gaps == [dict(kind='bond_holders', report_date='2026-06-30',
                         source_panel='unknown_1', reason='instrument_name_missing')]
    with pytest.raises(ValueError, match='标的身份'):
        parse(mixed_bonds(), 'bond_holders', STOCK)


@pytest.mark.parametrize('damage', ['unit', 'duplicate', 'date'])
def test_unidentified_report_does_not_hide_other_source_damage(damage):
    body = mixed_bonds()
    if damage == 'unit':
        body = body.replace('持有数量(万张)', '持有数量(股)', 1)
    elif damage == 'duplicate':
        body = body.replace('股东1', '股东0')
    else:
        body = body.replace('2026-06-30', '2026-02-30')
    with pytest.raises(ValueError):
        parse(body, 'bond_holders', STOCK, gaps=[])


def test_gap_contract_is_bounded_and_cannot_hide_other_sections():
    gap = dict(kind='bond_holders', report_date='2026-06-30',
               source_panel='unknown_1', reason='instrument_name_missing')
    for field, value in [('kind', 'top_holders'), ('reason', 'unknown'),
                         ('source_panel', ''), ('source_panel', 'x'*101),
                         ('report_date', 'bad')]:
        with pytest.raises(ValueError):
            validate_gaps([{**gap, field: value}])
    with pytest.raises(ValueError):
        validate_gaps([gap, copy.deepcopy(gap)])
    with pytest.raises(ValueError):
        validate_gaps([gap]*101)
    maximum = [{**gap, 'source_panel': str(i) + '定'*97} for i in range(100)]
    validate_gaps(maximum)
    assert len(json.dumps(maximum, ensure_ascii=False).encode()) < 65536
    with pytest.raises(ValueError, match='摘要'):
        unit_gaps(dict(source_gaps=[gap], source_gaps_digest='0'*64))


async def test_partial_security_published_then_later_security_and_retry():
    second = {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}
    c = configured([STOCK, second])
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=(
        mixed_bonds() if url.split('/')[-2] == STOCK['code'] else source(second['code'])).encode('gb18030'))
    with pytest.raises(CollectionSourceGap, match='可识别报告已确认归档'):
        await c.execute()
    assert c.http.request.await_count == 2
    assert len(c.ingest.events) == 2
    first = c.ingest.events[0].raw_payload
    assert all(first['reports'][k] for k in KINDS)
    assert first['gaps'][0]['source_panel'] == 'unknown_1'
    assert all(e.raw_payload['manifest'] is None for e in c.ingest.events)
    assert (await c.ingest.checkpoint(c.job_key))['cursor']['index'] == 0
    assert c.health()['status'] == 'source_gap'
    assert c.health()['failed_units'] == 0 and c.health()['source_gap_units'] == 1
    c.records.add_error.assert_not_awaited()
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(
        200, content=source(url.split('/')[-2]).encode('gb18030'))
    await c.execute(baseline_revision=await c.checkpoint_revision())
    assert c.ingest.events[-1].raw_payload['manifest'] is not None
    assert c.stats['source_identity_gaps'] == 0


@pytest.mark.parametrize('failure', ['source', 'archive'])
async def test_source_gap_does_not_mask_real_failure(failure):
    second = {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}
    c = configured([STOCK, second])
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=(
        mixed_bonds() if url.split('/')[-2] == STOCK['code'] else
        source(second['code']).replace('持有数量(股)', '持有数量(万股)') if failure == 'source' else
        source(second['code'])).encode('gb18030'))
    if failure == 'archive':
        c.confirmation.page_status.side_effect = RuntimeError('SQL unavailable')
    with pytest.raises((ValueError, RuntimeError)) as caught:
        await c.execute()
    assert not isinstance(caught.value, CollectionSourceGap)
    assert c.health()['status'] == 'error'
    assert c.http.request.await_count == 2
    assert (await c.ingest.checkpoint(c.job_key))['cursor']['index'] == 0


async def test_source_gap_waits_for_whole_round_confirmation():
    import asyncio
    from unittest.mock import AsyncMock

    c = configured()
    c.http.request.side_effect = lambda *args, **kwargs: httpx.Response(
        200, content=mixed_bonds().encode('gb18030'))
    confirming, release = asyncio.Event(), asyncio.Event()
    async def confirm(*args):
        confirming.set()
        await release.wait()
        return {'status': 'complete'}
    c.confirmation.page_status = AsyncMock(side_effect=confirm)
    task = asyncio.create_task(c.execute())
    try:
        await asyncio.wait_for(confirming.wait(), 2)
        assert not task.done() and c.health()['status'] == 'awaiting_archive'
        release.set()
        with pytest.raises(CollectionSourceGap):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_explicit_pending_conversion_preserves_source_facts_and_observation():
    reports = {kind: parse(source(), kind, STOCK) for kind in KINDS}
    old = make_envelope(source='ths', dataset='holders.reports', schema_version=4,
        business_key=STOCK['unified_code'], job_key='ths-holders-v1', run_id='pending-run-001',
        batch_id='pending-batch-001', payload=dict(page=1, unit=STOCK['unified_code'], reports=reports, manifest=None))
    new = convert(old.model_dump_json())
    assert new.raw_payload == {**old.raw_payload, 'gaps': []}
    assert new.observed_at == old.observed_at and new.batch_id == old.batch_id
    assert new.event_id != old.event_id and new.schema_version == 5
    with pytest.raises(ValueError):
        convert(new.model_dump_json())
