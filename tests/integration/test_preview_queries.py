"""New read paths against real SQL, with UUID-isolated schema ownership from conftest."""
import json
import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from empire.core.config import load_config
from empire.features.capital_actions.query import CapitalDataPlugin
from empire.features.data_browser.api import candidates
from empire.features.index_prices.query import IndexPriceDataPlugin
from empire.features.indices.query import IndexDataPlugin
from empire.features.industries.query import IndustryDataPlugin
from empire.features.kaipanla.normalization import digest
from empire.features.kaipanla.query import KaipanlaProductDataPlugin
from empire.features.kaipanla.repository import write_day
from empire.features.name_changes.query import NameDataPlugin
from empire.plugins.infra.mysql_store import make_engine
from tests.test_kaipanla_products import business_row

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1',
                                                        reason='Explicit isolated SQL integration')]


@pytest.fixture
def mysql():
    engine = make_engine(load_config()['mysql'])
    async def read(fn, *args):
        return fn(*args)
    yield SimpleNamespace(read_engine=engine, read=read)
    engine.dispose()


async def test_descending_same_date_cursor_and_historical_candidate_market(mysql):
    q = NameDataPlugin('security')
    q.mysql = mysql
    with mysql.read_engine.begin() as conn:
        conn.execute(text('INSERT INTO security_name_change(name_kind,record_key,unified_code,event_date,old_name,new_name,source_occurrences) '
            'VALUES(:kind,:key,:security,:day,:old,:name,1)'), [dict(kind='security', key=f'{i:064x}',
                security='000001.'+market, day='2026-10-09', old='旧公司', name='新公司')
                for i, market in enumerate(('SH', 'SZ', 'SZ'), 1)])
    first = await q.list_events('000001.SZ', limit=1, descending=True)
    second = await q.list_events('000001.SZ', after=first['next'], limit=1, descending=True)
    assert first['rows'][0]['record_key'] != second['rows'][0]['record_key']
    assert first['rows'][0]['unified_code'] == second['rows'][0]['unified_code'] == '000001.SZ'
    assert second['next'] is None
    choices = await candidates(mysql, '旧公司', 'names_security')
    assert {r['unified_code'] for r in choices} == {'000001.SH', '000001.SZ'}
    with pytest.raises(ValueError):
        await q.list_events('.SH')


async def test_industry_directory_has_complete_count_and_members_are_separate_pages(mysql):
    q = IndustryDataPlugin()
    q.mysql = mysql
    with mysql.read_engine.begin() as conn:
        conn.execute(text("INSERT INTO industry VALUES('881155','银行')"))
        conn.execute(text('INSERT INTO industry_member VALUES(:security,\'881155\',:name)'),
            [dict(security=f'{i:06}.SH', name='成员'+str(i)) for i in range(205)])
    directory = await q.directory()
    assert directory['rows'][0]['member_count'] == 205
    first = await q.list_members(industry='881155')
    second = await q.list_members(offset=200, industry='881155')
    assert first['total'] == second['total'] == 205
    assert len(first['rows']) == 200 and len(second['rows']) == 5
    assert (await q.directory('000204.SH'))['rows'][0]['member_count'] == 205


async def test_index_chart_full_range_dates_and_anomalous_candle(mysql):
    q = IndexPriceDataPlugin()
    q.mysql = mysql
    with mysql.read_engine.begin() as conn:
        conn.execute(text("INSERT INTO stock_index(index_code,name,source_group,members_available) VALUES('800000','测试指数','测试',1)"))
        conn.execute(text('INSERT INTO index_daily_price(index_code,trade_date,open,high,low,close,volume,amount) '
            "VALUES('800000',:day,10,:high,9,11,100,1000)"),
            [dict(day=date(2025, 1, 1)+timedelta(days=i), high=8 if i == 201 else 12) for i in range(241)])
    result = await q.chart_series('800000', '2025-01-01', '2025-12-31')
    assert len(result['rows']) == 241
    assert not result['rows'][201]['price_relation_valid']
    assert result['rows'][201]['close'] == 11
    for start, end in (('2026-01-01', '2025-01-01'), ('1980-01-01', '2026-01-01'), ('bad', '2026-01-01')):
        with pytest.raises(ValueError):
            await q.chart_series('800000', start, end)


async def test_index_directory_over_one_page_and_exact_market_reverse_query(mysql):
    q = IndexDataPlugin()
    q.mysql = mysql
    with mysql.read_engine.begin() as conn:
        conn.execute(text('INSERT INTO stock_index(index_code,name,source_group,members_available) VALUES(:code,:name,\'测试\',1)'),
            [dict(code=f'{800000+i}', name='指数'+str(i)) for i in range(205)])
        conn.execute(text('INSERT INTO stock_index_member VALUES(:index,:source,:security,:name)'),
            [dict(index='800000', source='000001', security='000001.SH', name='上海'),
             dict(index='800001', source='000001', security='000001.SZ', name='深圳')])
    first = await q.browse()
    second = await q.browse(after=first['next'])
    assert len(first['rows']) == 200 and len(second['rows']) == 5
    selected = await q.browse('members', selected_index='800000')
    assert {r['index_code'] for r in selected['rows']} == {'800000'}
    reverse = await q.browse('members', '000001.SH')
    assert {r['unified_code'] for r in reverse['rows']} == {'000001.SH'}


async def test_plan_date_status_and_exact_event_key_preserve_parallel_plans(mysql):
    q = CapitalDataPlugin('dividends')
    q.mysql = mysql
    with mysql.read_engine.begin() as conn:
        conn.execute(text('INSERT INTO dividend_plan VALUES(:security,:key,\'公司\',:day,:payload,:hash,:observed)'),
            [dict(security='600000.SH', key=f'{i:064x}', day=date(2026, 10, 9)+timedelta(days=i),
                  payload=json.dumps(dict(status='实施方案' if i != 2 else '预案', cash_per_share=i)),
                  hash='a'*64, observed=datetime(2026, 10, 11)) for i in range(3)])
    filtered = await q.list_events('600000', 'SH', start='2026-10-09', end='2026-10-10', status='实施方案')
    assert len(filtered) == 2
    exact = await q.list_events('600000', 'SH', record_key=f'{1:064x}')
    assert len(exact) == 1 and exact[0]['data']['cash_per_share'] == 1


async def test_trade_window_keeps_original_sequence_across_same_second_block_boundary(mysql):
    q = KaipanlaProductDataPlugin('trades')
    q.mysql = mysql
    row = business_row('trades')
    row['data']['fb'] = [['09:29:59' if i < 199 else '09:30:00', 10, 1, 10, 0, 1, 0, i] for i in range(450)]
    row['data'].update(Count=450, total=450)
    with mysql.read_engine.begin() as conn:
        write_day(conn, row, digest(row), datetime(2026, 10, 11))
    choices = await candidates(mysql, '', 'kaipanla_trades', 1)
    assert [r['unified_code'] for r in choices] == ['000001.SZ']
    assert await candidates(mysql, '000001.SZ', 'kaipanla_trades', 1) == choices
    assert not await candidates(mysql, '000001.SH', 'kaipanla_trades', 1)
    first = await q.page('SZ', '000001', '2021-01-04', start_time='09:30:00', end_time='09:30:00')
    second = await q.page('SZ', '000001', '2021-01-04', first['next_cursor'], start_time='09:30:00', end_time='09:30:00')
    assert first['seqs'] + second['seqs'] == list(range(199, 450))
    assert all(p[0] == '09:30:00' for p in first['points'] + second['points'])
    with pytest.raises(ValueError):
        await q.page('SZ', '000001', '2021-01-04', first['next_cursor'], start_time='09:30:00', end_time='09:31:00')
