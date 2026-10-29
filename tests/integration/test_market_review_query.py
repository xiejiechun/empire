"""Real schema read-only query, isolated by the shared integration fixture."""
import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.features.market_review.query import ReviewQuery, read_review
from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Owned SQL database opt-in')]


async def test_real_schema_read_only_snapshot_and_missing_calendar(private_business_database):
    engine = make_engine(load_config()['mysql'])
    day = date(2026, 10, 26)
    try:
        with engine.begin() as conn:
            with pytest.raises(ValueError, match='日历缺日'):
                read_review(conn, str(day), str(day))
            conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) '
                              'VALUES(:day,:trade,:at)'),
                         [dict(day=day-timedelta(days=i), trade=True, at=datetime(2026, 10, 27))
                          for i in range(31)])
            conn.execute(text('INSERT INTO yuanhang_limit_pool(trade_date,pool_type,source_total,'
                'filter_text,key_sha256,content_sha256,contract_version,observed_at) '
                'VALUES(:day,:pool,0,:filter,:hash,:hash,1,:at)'),
                [dict(day=day, pool=pool, filter='HS,GEM2STAR', hash='0'*64, at=datetime(2026, 10, 27))
                 for pool in ('limit_up_pool', 'open_limit_up_pool', 'limit_down_pool')])
        statements = []
        event.listen(engine, 'before_cursor_execute',
                     lambda conn, cursor, sql, params, context, many: statements.append(sql))
        async def read(fn):
            return fn()
        query = ReviewQuery()
        query.mysql = SimpleNamespace(read_engine=engine, read=read)
        result = await query.review(str(day), str(day))
        row = result['days'][0]
        assert row['up'] == 0 and row['sealed'] is None and row['height'] == 0
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
        assert any('READ ONLY' in s for s in statements)
    finally:
        engine.dispose()
