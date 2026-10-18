"""All sections form one admission boundary and one transactional dataset."""
import copy

import httpx
import pytest

from empire.contracts.data import make_envelope
from empire.contracts.holders import KINDS
from empire.plugins.collectors.ths_holders_source import parse
from empire.plugins.datasets.holders import HolderDataset
from scripts.migrate_holder_task import NEW, OLD, choose_policy
from tests.test_ths_holders import STOCK, configured, source


@pytest.mark.parametrize('section', ['tenholder', 'flowholder', 'bondholder'])
async def test_any_section_failure_publishes_nothing(section):
    collector = configured()
    bad = source().replace('id="' + section + '"', 'id="broken-' + section + '"')
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=bad.encode('gb18030'))
    with pytest.raises(ValueError):
        await collector.execute()
    assert collector.http.request.await_count == 1
    assert not collector.ingest.events
    assert (await collector.ingest.checkpoint(collector.job_key))['revision'] == 0


def test_archive_rejects_message_missing_or_invalid_section():
    reports = {kind: parse(source(), kind, STOCK) for kind in KINDS}
    envelope = make_envelope(source='ths', dataset='holders.reports', schema_version=5, business_key=STOCK['unified_code'],
        job_key='ths-holders-v1', batch_id='combined-batch-01', run_id='combined-run-01',
        payload=dict(page=1, unit=STOCK['unified_code'], reports=reports, manifest=None, gaps=[]))
    mapping = HolderDataset()
    assert mapping.normalize(envelope)['row_count'] == 33
    for kind in KINDS:
        missing = copy.deepcopy(envelope.raw_payload)
        del missing['reports'][kind]
        with pytest.raises(ValueError):
            mapping.normalize(envelope.model_copy(update={'raw_payload': missing}))
        damaged = copy.deepcopy(envelope.raw_payload)
        damaged['reports'][kind][0]['members'][0]['quantity'] = 'invalid'
        with pytest.raises(ValueError):
            mapping.normalize(envelope.model_copy(update={'raw_payload': damaged}))


def test_task_migration_preserves_user_policy_and_rejects_ambiguity():
    default = dict(mode='daily', enabled=False, interval_seconds=86400, daily_time='18:00',
                   request_retries=2, use_proxy=True, proxy_fallback=True, archived=False)
    changed = {**default, 'enabled': True, 'daily_time': '19:30', 'use_proxy': False}
    assert choose_policy({key: changed for key in OLD}, default) == changed
    assert choose_policy({}, default) == default
    assert choose_policy({NEW: changed, OLD[0]: default}, default) == changed
    with pytest.raises(ValueError, match='配置不同'):
        choose_policy({OLD[0]: changed, OLD[1]: default}, default)
