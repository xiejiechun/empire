import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, text

from empire.core.time import mysql_time
from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.parser import parse
from tests.capital_samples import issue_detail, source
from tests.integration.test_capital_archive import capital_db as _capital_db

capital_db = _capital_db

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


async def test_absence_history_preservation_cold_replay_and_recovery(capital_db):
    manager, query, collector, publish = capital_db
    if query.kind != 'additional_issues':
        return
    original = await publish(observed=datetime.now(UTC) - timedelta(hours=1))
    before = (await query.list_events())[0]
    state = await collector.ingest.checkpoint(collector.job_key)
    collector.http.request.side_effect = [httpx.Response(200, json=source(query.kind)),
                                          httpx.Response(200, json={'ErrorCode': -1005})]
    await collector.execute(fresh=True, baseline_revision=state['revision'])
    unavailable = (await query.list_events())[0]
    assert unavailable['data']['detail']['last_available'] == before['data']['detail']
    assert unavailable['data']['detail']['source_error_code'] == -1005
    assert all(check.status == 'pass' for check in await query.preparation_check())
    mysql, archive = manager.registry.get('mysql.store'), manager.registry.get('archive.worker')
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if query.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        await archive.fingerprints.invalidate(query.kind, query.source)
        state = await collector.ingest.checkpoint(collector.job_key)
        collector.http.request.side_effect = [httpx.Response(200, json=source(query.kind)),
                                              httpx.Response(200, json={'ErrorCode': -1005})]
        await collector.execute(baseline_revision=state['revision'])
        assert not writes and (await query.list_events())[0] == unavailable
        await archive.fingerprints.invalidate(query.kind, query.source)
        state = await collector.ingest.checkpoint(collector.job_key)
        collector.http.request.side_effect = [httpx.Response(200, json=source(query.kind)),
                                              httpx.Response(200, json=issue_detail())]
        await collector.execute(baseline_revision=state['revision'])
        assert (await query.list_events())[0] == before
        assert len(writes) == 1
        # A late old response cannot restore the no-data state over recovered detail.
        await publish(observed=original.observed_at)
        assert (await query.list_events())[0] == before and len(writes) == 1
        store = manager.registry.get('redis.store')
        assert await store.client.xlen(store.stream) == 0
        assert (await collector.records.list_error_summaries(collector.project_id))['total'] == 0
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_unknown_historical_row_is_excluded_only_by_exact_source_proof(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind != 'additional_issues':
        return
    await collector.execute()
    archive, mysql = manager.registry.get('archive.worker'), manager.registry.get('mysql.store')
    old_body = source(query.kind, code='688111')
    old_body['ResultSets'][0]['Content'][0][15] = 1002
    old = parse(query.kind, old_body, 10000)[0][0]
    async with archive.lock:
        await archive.fingerprints.invalidate(query.kind, query.source)
        with mysql.engine.begin() as conn:
            conn.execute(text('INSERT INTO additional_issue '
                '(record_key,unified_code,name,event_date,payload,content_hash,version_observed_at) '
                'VALUES (:record_key,:unified_code,:name,:event_date,:payload,:content_hash,:observed)'),
                {**old, 'unified_code': old['code']+'.'+old['market'], 'payload': json.dumps(old['data']),
                 'content_hash': digest(old), 'observed': mysql_time(datetime.now(UTC))})
    assert len(await query.list_events()) == 2
    assert all(check.status == 'pass' for check in await query.preparation_check())
    async with archive.lock:
        with mysql.engine.begin() as conn:
            conn.execute(text("UPDATE additional_issue SET payload=JSON_REMOVE(payload,'$.detail') "
                              "WHERE unified_code='688110.SH'"), {'source': query.source})
    assert any(check.status == 'fail' for check in await query.preparation_check())
