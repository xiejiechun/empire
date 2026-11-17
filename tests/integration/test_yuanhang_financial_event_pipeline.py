"""Financial source counterexamples through the shared archive and typed query."""
import os
from copy import deepcopy
from datetime import date, timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from scripts.yuanhang_financial_schema import OLD_ACTION_CHECK, financial_revision
from tests.integration.test_yuanhang_archive import native as native
from tests.integration.test_yuanhang_archive import publish
from tests.integration.test_yuanhang_typed_storage import archive
from tests.integration.test_yuanhang_typed_storage import storage as storage
from tests.test_yuanhang_financial_events import payload
from tests.test_yuanhang_payload import CODE
from tests.test_yuanhang_storage import envelope

pytestmark = [pytest.mark.integration,
    pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit private database')]


async def test_same_day_keyset_pagination_null_asof_and_content_audit(storage):
    mysql, q = storage
    p = payload()
    with mysql.engine.begin() as conn:
        archive(conn,envelope(p,financial_unit=True))
    first = await q.actions(CODE,limit=1)
    second = await q.actions(CODE,after=first['next'],limit=1)
    assert len(first['rows']) == len(second['rows']) == 1 and second['next'] is None
    assert first['rows'][0]['ex_date'] == second['rows'][0]['ex_date']
    assert first['rows'][0]['event_key'] != second['rows'][0]['event_key']
    assert await q.audit_financial(p) == []
    assert (await q.capital_as_of(CODE,'circulating','2019-12-31'))['shares'] == 80
    assert (await q.capital_as_of(CODE,'circulating','2020-01-01'))['shares'] is None
    assert await q.financial_quality(CODE) == dict(missing_circulating=1,ambiguous_action_dates=['2024-06-27'])
    with pytest.raises(ValueError,match='游标'):
        await q.actions(CODE,after='2024-06-27')
    for kind in ('total','free_float'):
        with pytest.raises(OperationalError,match='ck_yuanhang_capital_shares'),mysql.engine.begin() as conn:
            conn.execute(text('UPDATE yuanhang_capital SET shares=NULL WHERE capital_kind=:kind'),dict(kind=kind))


@pytest.mark.parametrize('interrupted',[False,True])
async def test_explicit_financial_migration_maps_every_old_event_and_preserves_content(storage,interrupted):
    mysql, q = storage
    p = payload()
    p['actions'] = [[(date(1998,1,1)+timedelta(days=i)).isoformat(),'0','0','0','0','0.1'] for i in range(601)]
    p['capital'][1][2] = '80'
    with mysql.engine.begin() as conn:
        archive(conn,envelope(p,financial_unit=True))
        conn.exec_driver_sql('ALTER TABLE yuanhang_corporate_action DROP PRIMARY KEY, DROP event_key, '
            'ADD PRIMARY KEY(unified_code,ex_date), DROP CHECK ck_yuanhang_action_values, '
            'ADD CONSTRAINT ck_yuanhang_action_values CHECK ' + OLD_ACTION_CHECK)
        conn.exec_driver_sql('ALTER TABLE yuanhang_capital DROP CHECK ck_yuanhang_capital_shares, '
            'MODIFY shares DECIMAL(28,10) NOT NULL, ADD CONSTRAINT ck_yuanhang_capital_shares CHECK(shares>0)')
        if interrupted:
            conn.exec_driver_sql('ALTER TABLE yuanhang_corporate_action ADD event_key '
                'CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER ex_date')
    with mysql.engine.connect() as conn:
        result = financial_revision(conn)
        assert set(result['changed']) == {'yuanhang_corporate_action','yuanhang_capital'}
        assert result['evidence']['actions']['rows'] == 601
        assert financial_revision(conn)['changed'] == []
    assert await q.audit_financial(p) == []


async def test_unknown_financial_shape_is_rejected_before_any_ddl(storage):
    mysql,_ = storage
    with mysql.engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE yuanhang_capital ADD INDEX unexpected(shares)')
    with mysql.engine.connect() as conn,pytest.raises(RuntimeError,match='拒绝修改'):
        financial_revision(conn)


async def test_financial_queue_commit_replay_hot_and_cold_duplicates_revision_and_late_old(native):
    _,c,q,store,worker = native
    p = payload()
    e = envelope(p,financial_unit=True)
    original_ack = worker.acknowledge
    async def fail_ack(ids):
        raise RuntimeError('fixture redis acknowledgement interrupted after SQL commit')
    worker.acknowledge = fail_ack
    try:
        with pytest.raises(RuntimeError,match='fixture redis'):
            await publish(c,worker,e)
        assert await store.client.xlen(store.stream) == 1
        assert await q.audit_financial(p) == []
    finally:
        # Invalidate under the same ownership as the resident worker. Otherwise
        # it can ACK a hot replay between our scan and DELETE, leaving an empty
        # queue and no proof for the next supposedly hot replay.
        async with worker.lock:
            worker.acknowledge = original_ack
            keys = [k async for k in store.client.scan_iter(match=store.prefix+':archive:fingerprint*')]
            if keys:
                await store.client.delete(*keys)
    writes = []
    def count(conn,cursor,sql,*args):
        if sql.startswith(('INSERT INTO yuanhang_','UPDATE yuanhang_','DELETE FROM yuanhang_')):
            writes.append(sql)
    event.listen(q.mysql.engine,'before_cursor_execute',count)
    event.listen(q.mysql.archive_engine,'before_cursor_execute',count)
    try:
        await worker.flush()
        assert writes == [] and await store.client.xlen(store.stream) == 0
        original_sql = worker.mysql.archive
        async def no_sql(*args,**kwargs):
            raise AssertionError('trusted financial replay must be SQL free')
        worker.mysql.archive = no_sql
        try:
            await publish(c,worker,e.model_copy(update=dict(observed_at=e.observed_at+timedelta(minutes=1))))
            assert await store.client.xlen(store.stream) == 0
        finally:
            worker.mysql.archive = original_sql
        revised = deepcopy(p)
        revised['actions'][0][-1] = '0.7'
        from empire.sources.yuanhang_payload import action_key
        revised['actions'].sort(key=lambda row:(row[0],action_key(row)))
        await publish(c,worker,envelope(revised,financial_unit=True,observed=e.observed_at+timedelta(hours=2)))
        assert writes and await q.audit_financial(revised) == []
        writes.clear()
        await publish(c,worker,e)
        assert writes == [] and await q.audit_financial(revised) == []
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine,'before_cursor_execute',count)
        event.remove(q.mysql.archive_engine,'before_cursor_execute',count)
