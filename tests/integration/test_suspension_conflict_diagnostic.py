"""Real Redis evidence for a rejected, conflicting complete-source month."""
import os
from datetime import date

import pytest

from empire.features.suspensions.collector import TdxSuspensionCollector
from empire.features.suspensions.contract import event_identity, normalize_source_row
from tests.integration.test_suspension_archive import suspension_db  # noqa: F401
from tests.prefetch_source import prefetch_http

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


async def test_conflict_survives_error_storage_without_publishing_or_moving_frontier(suspension_db):  # noqa: F811
    manager, query, _ = suspension_db
    collector = TdxSuspensionCollector(today=lambda: date(2004, 12, 28))
    collector.job_key, collector.project_id = query.job_key, query.project_id
    collector.ingest = manager.registry.get('ingest.publish')
    collector.query = query
    collector.confirmation = manager.registry.get('archive.confirmation')
    collector.records = manager.registry.get('collection.records')
    collector.http = prefetch_http()
    first = normalize_source_row(dict(sc=1, code='603517', name='合成旧简称',
        tprq='2004-12-27 09:30', fprq='2004-12-28 09:30', sj='停牌1天', sjcontent='重要公告'))

    async def download(day, **options):
        return [{**first, 'name': '合成新简称'} if day == '2004-12-28' else first], 1

    collector.download_day = download
    with pytest.raises(ValueError, match='内容冲突'):
        await collector.execute()
    errors = await collector.records.list_error_summaries(query.project_id)
    assert errors['total'] == 1
    detail = await collector.records.get_error(query.project_id, errors['rows'][0]['id'])
    assert detail['metadata']['conflict'] == dict(
        identity=event_identity(first), source_dates=['2004-12-27', '2004-12-28'],
        fields={'name': ['合成旧简称', '合成新简称']})
    assert detail['stage'] == 'suspension_validation'
    assert await collector.ingest.checkpoint(query.job_key) == {'revision': 0, 'cursor': {}}
    assert await query.list_events() == []
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
