"""Real SQL overview, tested only in a fixture-owned schema."""
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.market_review.market import read_market
from empire.features.market_review.query import ReviewQuery
from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Owned SQL database opt-in')]
DAY = date(2026, 10, 26)
PREVIOUS = date(2026, 10, 23)


@pytest.fixture
def market_engine(private_business_database):
    engine = make_engine(load_config()['mysql'])
    with engine.begin() as conn:
        days = [DAY + timedelta(days=i) for i in range(-30, 31)]
        conn.execute(text('INSERT INTO trade_calendar VALUES(:day,:trade,:at)'),
                     [dict(day=d, trade=d.weekday() < 5, at=datetime(2026, 10, 26)) for d in days])
        conn.execute(text('INSERT INTO yuanhang_limit_pool VALUES(:day,:pool,0,:filter,:hash,:hash,1,:at)'),
            [dict(day=d, pool=p, filter='HS,GEM2STAR,ST', hash='0'*64, at=datetime(2026, 10, 26))
             for d in days if d.weekday() < 5 for p in ('limit_up_pool', 'limit_down_pool')])
        conn.execute(text('INSERT INTO yuanhang_daily_price '
            '(unified_code,trade_date,open,high,low,close,amount_yuan) VALUES(:code,:day,10,10,10,10,:amount)'),
            [dict(code='600000.SH', day=DAY, amount='123456789.25'),
             dict(code='600001.SH', day=DAY, amount=0),
             dict(code='600000.SH', day=PREVIOUS, amount='23456789.25')])
        conn.execute(text('INSERT INTO yuanhang_index_daily_price(index_code,trade_date,close,volume) '
            'VALUES(:code,:day,:close,1)'),
            [dict(code='1A0001', day=DAY, close=110), dict(code='1A0001', day=PREVIOUS, close=100),
             dict(code='399300', day=DAY, close=220), dict(code='399300', day=PREVIOUS, close=200)])
        conn.execute(text('INSERT INTO graymarket_day VALUES(:day,:hash,3,1)'), dict(day=DAY, hash='0'*64))
        conn.execute(text('INSERT INTO graymarket_daily VALUES '
            '(:day,:code,:name,:dark,:visible,:main,1,10,:change,:time,:rank)'),
            [dict(day=DAY, code=f'60000{i}.SH', name=f'样本{i}', dark=v, visible=0, main=v,
                  change=c, time='153000', rank=i+1) for i, (v, c) in enumerate(((5, 1), (-5, -1), (0, 0)))])
    try:
        yield engine
    finally:
        engine.dispose()


async def test_overview_snapshot_decimal_zero_scope_and_no_writes(market_engine):
    statements = []
    event.listen(market_engine, 'before_cursor_execute',
                 lambda conn, cursor, sql, params, context, many: statements.append(sql))
    async def read(fn):
        return fn()
    query = ReviewQuery()
    query.mysql = SimpleNamespace(read_engine=market_engine, read=read)
    result = await query.market(str(DAY))
    assert result['status'] == 'closed'
    assert result['previous_date'] == PREVIOUS and result['next_date'] == date(2026, 10, 27)
    assert result['limit_up'] == result['limit_down'] == result['first_boards'] == result['chain'] == 0
    assert result['amount_yuan'] == Decimal('123456789.25')
    assert result['amount_change_yuan'] == Decimal('100000000')
    assert result['price_count'] == 2 and result['previous_price_count'] == 1
    assert result['main_flow_yuan'] == 0 and result['fund_count'] == 3
    assert result['capital']['visible_flow_yuan'] == 0
    assert result['capital']['dark_flow_yuan'] == 0
    assert result['capital']['inflow'] == [dict(unified_code='600000.SH', name='样本0',
        amount_yuan=Decimal(5), change_ratio=Decimal(1))]
    assert [r['unified_code'] for r in result['capital']['outflow']] == ['600001.SH']
    assert (result['advance'], result['decline'], result['flat']) == (1, 1, 1)
    assert result['indices'][0]['change'] == 10
    assert result['indices'][4]['code'] == '399300' and result['indices'][4]['change'] == 10
    assert result['indices'][5]['close'] is None
    assert all(item['change'] is None for item in result['overseas'])
    assert any('READ ONLY' in sql for sql in statements)
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in statements)


def test_gaps_integrity_calendar_and_no_previous_day_substitution(market_engine):
    with market_engine.begin() as conn:
        conn.execute(text('UPDATE yuanhang_daily_price SET amount_yuan=NULL WHERE unified_code=:code'), {'code': '600000.SH'})
        conn.execute(text('UPDATE graymarket_day SET row_count=4'))
        conn.execute(text("UPDATE yuanhang_limit_pool SET source_total=1 WHERE trade_date=:day AND pool_type='limit_up_pool'"), {'day': DAY})
        conn.execute(text('DELETE FROM yuanhang_index_daily_price WHERE trade_date=:day'), {'day': PREVIOUS})
    with market_engine.connect() as conn:
        result = read_market(conn, str(DAY))
        assert result['amount_yuan'] is None and result['amount_change_yuan'] is None
        assert result['main_flow_yuan'] is None and result['advance'] is None
        assert all(result['capital'][k] is None for k in ('visible_flow_yuan', 'dark_flow_yuan', 'inflow', 'outflow'))
        assert result['capital']['sectors']['inflow'] is None
        assert result['limit_up'] is None and result['limit_down'] == 0
        assert result['indices'][0]['close'] == 110 and result['indices'][0]['change'] is None
        assert len(result['issues']) >= 3
        for day, now, status in [
            (DAY, datetime(2026, 10, 26, 15, 29, tzinfo=CHINA), 'pending'),
            (DAY, datetime(2026, 10, 25, 18, tzinfo=CHINA), 'future'),
            (date(2026, 10, 25), datetime(2026, 10, 26, 18, tzinfo=CHINA), 'rest'),
            (date(1990, 1, 1), datetime(2026, 10, 26, 18, tzinfo=CHINA), 'unknown'),
        ]:
            row = read_market(conn, str(day), now=now)
            assert row['status'] == status
            assert row['amount_yuan'] is None and row['limit_up'] is None
            assert row['capital']['inflow'] is None and row['capital']['dark_flow_yuan'] is None
    with market_engine.begin() as conn:
        conn.execute(text('DELETE FROM trade_calendar WHERE trade_date=:day'), {'day': date(2026, 10, 25)})
    with market_engine.connect() as conn:
        result = read_market(conn, str(DAY))
        assert result['previous_date'] is None
        assert result['indices'][0]['change'] is None and result['chain'] is None


def test_continuous_boards_and_same_index_code_base(market_engine):
    with market_engine.begin() as conn:
        conn.execute(text("UPDATE yuanhang_limit_pool SET source_total=:n WHERE trade_date=:day AND pool_type='limit_up_pool'"),
                     [dict(day=PREVIOUS, n=1), dict(day=DAY, n=2)])
        conn.execute(text('INSERT INTO yuanhang_limit_member '
            '(trade_date,pool_type,unified_code,identity_basis,name,market_type,high_days) '
            "VALUES(:day,'limit_up_pool',:code,'source','测试','HS','9天5板')"),
            [dict(day=PREVIOUS, code='600000.SH'), dict(day=DAY, code='600000.SH'),
             dict(day=DAY, code='600001.SH')])
        conn.execute(text("INSERT INTO yuanhang_index_daily_price(index_code,trade_date,close,volume) VALUES('1B0300',:day,330,1)"), {'day': DAY})
    with market_engine.connect() as conn:
        row = read_market(conn, str(DAY))
        assert row['first_boards'] == 1 and row['chain'] == 1
        assert row['indices'][4]['code'] == '1B0300'
        assert row['indices'][4]['close'] == 330 and row['indices'][4]['change'] is None


def test_capital_top_five_sign_ties_precision_and_date_scope(market_engine):
    with market_engine.begin() as conn:
        conn.execute(text('DELETE FROM graymarket_daily'))
        conn.execute(text('UPDATE graymarket_day SET row_count=14'))
        conn.execute(text('INSERT INTO graymarket_daily VALUES '
            '(:day,:code,:name,:dark,:visible,:main,1,10,:change,:time,:rank)'),
            [dict(day=DAY, code=f'6000{i:02d}.SH', name=f'资金{i}', dark=v-2, visible=2, main=v,
                  change=Decimal('0.0123456789'), time='153000', rank=i+1)
             for i, v in enumerate([0, 0, 7, 7, 6, 5, 4, 3, -8, -8, -7, -6, -5, -4])]
            + [dict(day=PREVIOUS, code='600099.SH', name='前日巨额', dark=10**20,
                    visible=0, main=10**20, change=0, time='153000', rank=1)])
    with market_engine.connect() as conn:
        row = read_market(conn, str(DAY))
        capital = row['capital']
        assert [r['unified_code'] for r in capital['inflow']] == [f'6000{i:02d}.SH' for i in range(2, 7)]
        assert [r['unified_code'] for r in capital['outflow']] == [f'6000{i:02d}.SH' for i in range(8, 13)]
        assert capital['inflow'][0]['change_ratio'] == Decimal('0.0123456789')
        assert capital['visible_flow_yuan'] == 28
        assert capital['dark_flow_yuan'] + capital['visible_flow_yuan'] == row['main_flow_yuan'] == -6
        prior = read_market(conn, str(PREVIOUS))
        assert prior['capital']['inflow'] is None


@pytest.mark.parametrize('amount', [0, -7])
def test_capital_complete_day_without_positive_flows_is_known_empty(market_engine, amount):
    with market_engine.begin() as conn:
        conn.execute(text('UPDATE graymarket_daily SET dark_flow=:v,main_flow=:v'), {'v': amount})
    with market_engine.connect() as conn:
        row = read_market(conn, str(DAY))
        assert row['capital']['inflow'] == []
        assert len(row['capital']['outflow']) == (3 if amount < 0 else 0)
        assert row['capital']['dark_flow_yuan'] == 3 * amount
