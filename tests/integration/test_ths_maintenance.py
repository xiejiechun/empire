"""SQL-confirmed planning and hot-cache timestamps through real archival."""
import asyncio
import os

import pytest
from sqlalchemy import text

from tests.integration.test_financial_archive import financial_db
from tests.integration.test_ths_capital_archive import capital

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private SQL/Redis required')]
__all__ = ['financial_db', 'capital']


async def test_financial_confirmed_no_change_and_fresh(financial_db):
    m, q, c, _ = financial_db
    with q.mysql.engine.begin() as conn:
        conn.execute(text("INSERT INTO stock(unified_code,name) VALUES('601139.SH','深圳燃气')"))
    await asyncio.wait_for(c.execute(), 20)
    proofs = await q.collection_units()
    assert proofs['SH:601139']['count'] == 2
    before = c.http.request.await_count
    await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)
    assert c.http.request.await_count == before
    assert c.stats['reused_units'] == 1
    # Explicit fresh still discovers old-period corrections.
    await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), 20)
    assert c.http.request.await_count == before + 1
    assert len(await q.list_statements('601139')) == 2
    store = m.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    assert (await q.collection_units())['SH:601139']['stamp'] >= proofs['SH:601139']['stamp']


async def test_capital_confirmed_no_change_and_fresh(capital):
    _, c, q, store, _ = capital
    await asyncio.wait_for(c.execute(), 20)
    proofs = await q.collection_units()
    assert proofs['601139.SH']['count'] > 0
    before = c.http.request.await_count
    await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)
    assert c.http.request.await_count == before
    assert c.stats['reused_units'] == 1
    await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), 20)
    assert c.http.request.await_count == before + 1
    assert await store.client.xlen(store.stream) == 0
