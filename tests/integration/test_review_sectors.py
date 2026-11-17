"""Current membership, complete-day funding and explicit partial coverage."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from empire.features.industries.api import STATE_DATASET
from empire.features.industries.dataset import CONTRACT_VERSION, digest, validate
from empire.features.market_review.market import read_market
from empire.features.market_review.query import ReviewQuery
from tests.integration import test_review_market as base

DAY, PREVIOUS = base.DAY, base.PREVIOUS
market_engine = base.market_engine
pytestmark = base.pytestmark

NAMESPACE = 'empire:test:review_sectors'


def publish(conn, industries, namespace=NAMESPACE):
    count = validate(industries)
    conn.execute(text('INSERT INTO industry VALUES(:code,:name)'), industries)
    conn.execute(text('INSERT INTO industry_member VALUES(:security,:industry,:name)'),
        [dict(security=f'{code}.SH', industry=i['code'], name=name)
         for i in industries for code, name in i['members']])
    state = dict(contract_version=CONTRACT_VERSION, digest=digest(industries),
                 industry_count=len(industries), member_count=count, observed_at=datetime.now(UTC).isoformat())
    conn.execute(text('INSERT INTO collection_state VALUES(:namespace,:project,:source,:dataset,:payload,:at)'),
        dict(namespace=namespace, project='ths-industries', source='ths', dataset=STATE_DATASET,
             payload=json.dumps(state), at=datetime.now().replace(tzinfo=None)))


@pytest.fixture
def sectors_engine(market_engine):
    with market_engine.begin() as conn:
        conn.execute(text('UPDATE graymarket_daily SET dark_flow=:value,main_flow=:value WHERE unified_code=:code'),
            [dict(code='600000.SH', value=50), dict(code='600001.SH', value=-20)])
        publish(conn, [dict(code='881001', name='完整流入', members=[['600000', '来源名A']]),
                       dict(code='881002', name='部分流出', members=[['600001', '来源名B'], ['600010', '缺资金']]),
                       dict(code='881003', name='真实零', members=[['600002', '来源名C']]),
                       dict(code='881004', name='无覆盖', members=[['600011', '也缺资金']])])
    return market_engine


async def test_current_membership_historical_flow_coverage_namespace_and_read_only(sectors_engine):
    statements = []
    event.listen(sectors_engine, 'before_cursor_execute',
                 lambda conn, cursor, sql, params, context, many: statements.append(sql))
    async def read(fn):
        return fn()
    query = ReviewQuery(NAMESPACE)
    query.mysql = SimpleNamespace(read_engine=sectors_engine, read=read)
    row = await query.market(str(DAY))
    sector = row['capital']['sectors']
    assert sector['issue'] == '' and sector['industry_count'] == 4
    assert (sector['complete_count'], sector['partial_count'], sector['uncovered_count']) == (2, 1, 1)
    assert sector['inflow'] == [dict(industry_code='881001', name='完整流入', amount_yuan=50,
                                   member_count=1, covered_count=1)]
    assert sector['outflow'] == [dict(industry_code='881002', name='部分流出', amount_yuan=-20,
                                    member_count=2, covered_count=1)]
    assert datetime.fromisoformat(sector['basis_observed_at']).date() > DAY
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in statements)
    with sectors_engine.connect() as conn:
        # A valid proof in another namespace cannot authorize this namespace.
        unknown = read_market(conn, str(DAY), namespace='another')
        assert unknown['main_flow_yuan'] == 30
        assert unknown['capital']['sectors']['inflow'] is None
        assert read_market(conn, str(PREVIOUS), namespace=NAMESPACE)['capital']['sectors']['inflow'] is None


@pytest.mark.parametrize('fault', ['same_count_members', 'digest', 'version', 'future', 'shape', 'source', 'dataset', 'missing'])
def test_invalid_current_proof_hides_only_sector_totals(sectors_engine, fault):
    with sectors_engine.begin() as conn:
        if fault == 'same_count_members':
            conn.execute(text("UPDATE industry_member SET unified_code='600012.SH' WHERE unified_code='600010.SH'"))
        elif fault == 'source':
            conn.execute(text("UPDATE collection_state SET source='unknown'"))
        elif fault == 'dataset':
            conn.execute(text("UPDATE collection_state SET dataset='another.snapshot'"))
        elif fault == 'missing':
            conn.execute(text('DELETE FROM collection_state'))
        else:
            state = json.loads(conn.execute(text('SELECT payload FROM collection_state')).scalar_one())
            if fault == 'digest':
                state['digest'] = '0' * 64
            if fault == 'version':
                state['contract_version'] = 0
            if fault == 'future':
                state['observed_at'] = '2099-01-01T00:00:00+00:00'
            if fault == 'shape':
                state = []
            conn.execute(text('UPDATE collection_state SET payload=:payload'), {'payload': json.dumps(state)})
    with sectors_engine.connect() as conn:
        row = read_market(conn, str(DAY), namespace=NAMESPACE)
        assert row['main_flow_yuan'] == 30 and len(row['capital']['inflow']) == 1
        assert row['capital']['sectors']['inflow'] is None
        assert row['capital']['sectors']['outflow'] is None
        assert row['capital']['sectors']['issue']


def test_partial_zero_known_empty_and_incomplete_fund_day(sectors_engine):
    with sectors_engine.begin() as conn:
        conn.execute(text('UPDATE graymarket_daily SET dark_flow=0,main_flow=0'))
    with sectors_engine.connect() as conn:
        sector = read_market(conn, str(DAY), namespace=NAMESPACE)['capital']['sectors']
        assert sector['inflow'] == sector['outflow'] == []
        assert sector['partial_count'] == sector['uncovered_count'] == 1
    with sectors_engine.begin() as conn:
        conn.execute(text('UPDATE graymarket_day SET row_count=4'))
    with sectors_engine.connect() as conn:
        assert read_market(conn, str(DAY), namespace=NAMESPACE)['capital']['sectors']['inflow'] is None


def test_top_five_decimal_sort_ties_and_member_revision(market_engine):
    values = [8, 8, 7, 6, 5, 4, -8, -8, -7, -6, -5, -4]
    with market_engine.begin() as conn:
        conn.execute(text('DELETE FROM graymarket_daily'))
        conn.execute(text('UPDATE graymarket_day SET row_count=12'))
        conn.execute(text('INSERT INTO graymarket_daily VALUES '
            '(:day,:code,:name,:amount,0,:amount,1,10,0,:time,:rank)'),
            [dict(day=DAY, code=f'600{i:03d}.SH', name=f'证券{i}', amount=10**20 * v + v,
                  time='153000', rank=i+1) for i, v in enumerate(values)])
        publish(conn, [dict(code=f'881{i:03d}', name=f'行业{i}', members=[[f'600{i:03d}', f'证券{i}']])
                       for i in range(len(values))])
    with market_engine.connect() as conn:
        sector = read_market(conn, str(DAY), namespace=NAMESPACE)['capital']['sectors']
        assert [r['industry_code'] for r in sector['inflow']] == [f'881{i:03d}' for i in range(5)]
        assert [r['industry_code'] for r in sector['outflow']] == [f'881{i:03d}' for i in range(6, 11)]
        assert sector['inflow'][0]['amount_yuan'] == 8 * 10**20 + 8
    # An explicit current snapshot revision changes the historical recomputation.
    with market_engine.begin() as conn:
        conn.execute(text("UPDATE industry SET name='新行业名' WHERE industry_code='881000'"))
    with market_engine.connect() as conn:
        assert read_market(conn, str(DAY), namespace=NAMESPACE)['capital']['sectors']['inflow'] is None


def test_no_current_members_covered_is_unknown_not_known_empty(market_engine):
    with market_engine.begin() as conn:
        publish(conn, [dict(code='881001', name='无覆盖行业', members=[['600010', '缺资金']])])
    with market_engine.connect() as conn:
        data = read_market(conn, str(DAY), namespace=NAMESPACE)
        sector = data['capital']['sectors']
        assert data['main_flow_yuan'] is not None
        assert sector['inflow'] is None and sector['outflow'] is None
        assert sector['industry_count'] == sector['uncovered_count'] == 1
        assert sector['basis_observed_at'] and '未覆盖' in sector['issue']
