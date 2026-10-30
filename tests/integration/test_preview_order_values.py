"""Populated formal-query counterexamples; private UUID database only."""

import json
import os
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.desktop_bridge.preview import read
from empire.features.margin.query import derived
from empire.plugins.infra.collection_state import save_state
from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private MySQL opt-in')]


@pytest.fixture
def queries():
    cfg = load_config()
    manager, engine = build_manager(cfg), make_engine(cfg['mysql'])

    async def execute(fn, *args):
        return fn(*args)

    def get(capability):
        service = manager.entries[manager.providers[capability]].plugin
        service.mysql = SimpleNamespace(read_engine=engine, read=execute)
        return service

    try:
        yield SimpleNamespace(get=get), engine
    finally:
        engine.dispose()


async def drain(registry, project, field, direction, filters=None):
    cursor, rows = None, []
    for _ in range(20):
        view = {'tdx-dividends': 'dividends', 'sina-news': 'news'}.get(project, 'records')
        result = await read(registry, project, view,
                            filters or {}, cursor, dict(field=field, direction=direction))
        assert len(result['rows']) <= 50
        rows.extend(result['rows'])
        cursor = result['next']
        if cursor is None:
            return rows
    pytest.fail('排序游标未收敛')


async def test_json_decimal_nulls_ties_and_cross_task_cursor(queries):
    registry, engine = queries
    rows = []
    for i in range(123):
        value = None if i % 7 == 0 else str(Decimal('900719925474099.123456789') + Decimal(i % 5) / 1000)
        rows.append(dict(key=f'{i:064x}', code='000001.SZ' if i % 3 else '600000.SH',
                         payload=json.dumps(dict(cash_per_share=value)), value=value))
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO dividend_plan '
                          '(record_key,unified_code,name,event_date,payload,content_hash,version_observed_at) '
                          "VALUES (:key,:code,'测试','2025-12-31',:payload,:key,'2026-10-29')"), rows)
    for direction in ('asc', 'desc'):
        result = await drain(registry, 'tdx-dividends', 'cash_per_share', direction, dict(code='000001'))
        expected = sorted([r for r in rows if r['code'] == '000001.SZ'], key=lambda r: (
            r['value'] is None, Decimal(r['value'] or 0) * (1 if direction == 'asc' else -1), r['key']))
        assert [r['record_key'] for r in result] == [r['key'] for r in expected]
        assert len(result) == len({r['record_key'] for r in result}) == 82
    first = await read(registry, 'tdx-dividends', 'dividends', {}, order=dict(field='cash_per_share', direction='asc'))
    with pytest.raises(ValueError, match='排序或筛选'):
        await read(registry, 'tdx-rights-issues', 'rights_issues', {}, first['next'],
                   dict(field='rights_price', direction='asc'))


async def test_derived_fields_are_computed_before_paging_and_keep_previous_day(queries):
    registry, engine = queries
    rows = []
    first = date(2026, 1, 1)
    for i in range(115):
        row = dict(unified_code='000001.SZ', trade_date=first + timedelta(days=i),
                   market_volume=Decimal(i % 9), market_turnover=Decimal(i % 13),
                   close_price=None if i % 7 == 0 else Decimal('10.12345678'),
                   financing_balance=Decimal(i + 10), financing_buy=Decimal(i % 11),
                   lending_balance=Decimal(i % 5), lending_sell=Decimal(i % 3))
        rows.append(row)
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO margin_daily (' + ','.join(rows[0]) + ') VALUES ('
                          + ','.join(':' + k for k in rows[0]) + ')'), rows)
    expected = []
    for i, row in enumerate(rows):
        value = {**row, 'previous_financing': rows[i - 1]['financing_balance'] if i else None,
                 'previous_lending': rows[i - 1]['lending_balance'] if i else None}
        value.update(derived(value))
        if i >= 5:
            expected.append(value)
    for field in ('financing_repaid', 'lending_repaid', 'lending_amount', 'margin_difference',
                  'financing_buy_pct', 'lending_sell_pct', 'first_source_row'):
        for direction in ('asc', 'desc'):
            result = await drain(registry, 'tdx-margin', field, direction,
                                 dict(code='000001', start=(first + timedelta(days=5)).isoformat()))
            ordered = sorted(expected, key=lambda r: (
                r[field] is None, (r[field] or 0) * (1 if direction == 'asc' else -1), r['trade_date']))
            assert [r['trade_date'] for r in result] == [r['trade_date'].isoformat() for r in ordered], field
            assert len(result) == len({r['trade_date'] for r in result}) == 110


async def test_long_text_uses_full_value_and_blank_is_not_zero(queries):
    registry, engine = queries
    rows = [dict(id=i, content='' if i % 17 == 0 else '完整中文正文' * 300 + f'{125-i:03}')
            for i in range(1, 126)]
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO finance_news '
                          '(source,news_id,title,content,published_at,source_updated_at,is_important,tags,url,first_seen_at,version_observed_at) '
                          "VALUES ('sina',:id,'测试',:content,'2026-10-29','2026-10-29',0,'[]','','2026-10-29','2026-10-29')"), rows)
    for direction in ('asc', 'desc'):
        result = await drain(registry, 'sina-news', 'content', direction)
        nonempty = sorted([r for r in rows if r['content']], key=lambda r: r['content'], reverse=direction == 'desc')
        expected = nonempty + [r for r in rows if not r['content']]
        assert [r['news_id'] for r in result] == [r['id'] for r in expected]
        assert len(result) == len({r['news_id'] for r in result}) == 125


async def test_listing_status_orders_the_formal_availability_proof(queries):
    registry, engine = queries
    query = registry.get('listings.query')
    rows = [dict(code=f'{i:06}.SZ', hash=f'{i:064x}') for i in range(101)]
    units = {f'SZ:{i:06}': dict(availability_contract=1, availability='unavailable',
                              source_status_code=10001) for i in range(101) if i % 3 == 0}
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO stock_listing '
                          '(unified_code,listing_date,content_hash,contract_version,version_observed_at) '
                          "VALUES (:code,'2020-01-01',:hash,2,'2026-10-29')"), rows)
        save_state(conn, query.namespace, 'ths-listings', 'ths', 'listing.detail', dict(units=units), {})
    for direction in ('asc', 'desc'):
        result = await drain(registry, 'ths-listings', 'detail_status', direction)
        status = [r['detail_status'] for r in result]
        assert status == sorted(status, reverse=direction == 'desc')
        assert len(result) == len({r['unified_code'] for r in result}) == 101
        assert status.count('unavailable') == 34


async def test_suspension_source_day_sort_keeps_compound_identity(queries):
    registry, engine = queries
    with engine.begin() as conn:
        # Same record hash and effective date in different securities are two
        # source records. Calendar occurrence order intentionally runs backwards.
        for i in range(61):
            params = dict(code=f'{i:06}.SZ', day=date(2026, 1, 1) + timedelta(days=60-i), key='a' * 64)
            conn.execute(text('INSERT INTO suspension_event '
                              '(unified_code,name,suspended_at,resumed_at,resume_key,record_key,source_dates_known,suspension_type,source_note,reason,version_observed_at) '
                              "VALUES (:code,'测试','2020-01-01',NULL,'1000-01-01',:key,1,'','','','2026-10-29')"), params)
            conn.execute(text('INSERT INTO suspension_source_date '
                              '(source_date,unified_code,suspended_at,resume_key,record_key) '
                              "VALUES (:day,:code,'2020-01-01','1000-01-01',:key)"), params)
    cursor, rows = None, []
    while True:
        result = await read(registry, 'tdx-suspensions', 'events', dict(start='2026-01-01', end='2026-03-31'),
                            cursor, dict(field='source_dates', direction='asc'))
        rows.extend(result['rows'])
        cursor = result['next']
        if cursor is None:
            break
    assert [r['unified_code'] for r in rows] == [f'{i:06}.SZ' for i in reversed(range(61))]
    assert all(r['suspended_at'].startswith('2020-01-01') for r in rows)
    assert [r['source_dates'][0] for r in rows] == sorted(r['source_dates'][0] for r in rows)
