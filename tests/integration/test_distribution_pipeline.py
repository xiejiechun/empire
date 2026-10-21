"""Isolated official ingest/archive/query proof; never production mutations."""
import os
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text

from empire.features.capital_actions.contract import digest
from empire.plugins.infra.collection_state import read_state, save_state
from tests.integration import test_capital_archive

capital_db = test_capital_archive.capital_db

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly'),
    pytest.mark.parametrize('capital_db', ['dividends'], indirect=True)]
SCOPE = dict(codes=['688110'], start='2026-01-01', end='2026-10-20')


@pytest.fixture(autouse=True)
def bounded_period(monkeypatch):
    # This test exercises one complete synthetic source unit, not period discovery.
    monkeypatch.setattr('empire.features.capital_actions.dividend_history.report_periods',
                        AsyncMock(return_value=['2025-12-31']))


async def test_official_source_archive_decimal_and_sql_only_readiness(capital_db, monkeypatch):
    manager, query, collector, _ = capital_db
    await collector.execute()
    mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
    before = await query.list_events()
    mutations = []
    def record(conn, cursor, statement, params, context, many):
        if statement.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE'):
            mutations.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', record)
    event.listen(mysql.read_engine, 'before_cursor_execute', record)
    try:
        result = await query.distribution_summary(SCOPE)
        assert result['state'] == '已计算'
        assert result['securities'][0]['cash_per_share'] == '0.6'  # Source 6 yuan / ten.
        assert result['securities'][0]['cash_per_ten'] == '6'
        assert result['securities'][0]['rows'][0]['record_key'] == before[0]['record_key']
        assert result['securities'][0]['unit_content_hash'] == digest(before)
        empty = await query.distribution_summary({**SCOPE, 'end': '2026-06-01'})
        assert empty['state'] == '已计算' and empty['securities'][0]['cash_per_share'] == '0'
        boundary = await query.distribution_summary({**SCOPE, 'start': '2026-06-02', 'end': '2026-06-02'})
        assert boundary['securities'][0]['cash_per_share'] == '0.6'
        historic = await query.distribution_summary({**SCOPE, 'purpose': 'historical_signal'})
        assert historic['state'] == '来源受限' and not historic['securities']
        # Disable optional evidence at the context boundary, not the shared service.
        original = query.context.optional
        monkeypatch.setattr(query.context, 'optional', lambda key: None if key == 'redis.store' else original(key))
        sql_only = await query.distribution_summary(SCOPE)
        assert sql_only['state'] == '已计算'
        assert sql_only['observed_at'] == result['observed_at']
        assert await query.list_events() == before and not mutations
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', record)
        event.remove(mysql.read_engine, 'before_cursor_execute', record)


@pytest.mark.parametrize('damage', ['key', 'content', 'missing', 'proof'])
async def test_equal_counts_or_empty_projection_cannot_bypass_full_unit_proof(capital_db, damage):
    manager, query, collector, _ = capital_db
    await collector.execute()
    mysql = manager.registry.get('mysql.store')
    before = await query.list_events()
    with mysql.engine.begin() as conn:
        if damage == 'proof':
            previous = read_state(conn, query.namespace, query.project_id, query.source, lock=True)
            changed = deepcopy(previous)
            changed['units'].pop('SH:688110')
            save_state(conn, query.namespace, query.project_id, query.source, query.kind+'.unit', changed, previous)
        else:
            sql = {'key': f"UPDATE {query.table} SET record_key=REPEAT('f',64)",
                'content': f"UPDATE {query.table} SET name='test changed content'",
                'missing': f'DELETE FROM {query.table}'}[damage]
            conn.execute(text(sql))  # Only UUID private database; full-engine ownership guard active.
    result = await query.distribution_summary({**SCOPE, 'end': '2026-06-01'})
    assert result['state'] == '数据阻断' and result['securities'] == []
    if damage == 'proof':
        assert await query.list_events() == before
