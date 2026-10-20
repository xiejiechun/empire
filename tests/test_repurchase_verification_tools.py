"""Real private SQL positive path, exact guard negatives and cancellation ownership."""
import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('repurchase_capacity')


def test_exact_metadata_does_not_relax_session_or_sql_guard(capacity):
    storage=capacity.RepurchaseCapacityStorage(dict(host='test',port=13348,user='test'),{},'a'*32,'b'*64,'production')
    storage.server_uuid='private'
    conn=Mock()
    conn.engine.url.database=storage.database
    raw=conn.connection.cursor.return_value
    raw.fetchone.return_value=('private',storage.database)
    explain='EXPLAIN SELECT * FROM stock_repurchase_plan LIMIT 1'
    storage.explain_sql.add(explain)
    for sql in ('ANALYZE TABLE stock_repurchase_plan',explain):
        storage.guard(conn,None,sql,(),None,False)
        for actual in [('production',storage.database),('private','empire')]:
            raw.fetchone.return_value=actual
            with pytest.raises(ValueError,match='实际实例'):
                storage.guard(conn,None,sql,(),None,False)
        raw.fetchone.return_value=('private',storage.database)
    for sql in ('ANALYZE TABLE stock',explain+'; DELETE FROM stock','SELECT * FROM empire.stock'):
        with pytest.raises(ValueError):
            storage.guard(conn,None,sql,(),None,False)
    storage.explain_sql.add('EXPLAIN SELECT * FROM empire.stock')
    with pytest.raises(ValueError):
        storage.guard(conn,None,'EXPLAIN SELECT * FROM empire.stock',(),None,False)


def test_equal_count_different_set_and_content_fail(capacity):
    live=importlib.import_module('repurchase_verification')
    from empire.features.repurchases.contract import normalize
    from tests.test_repurchases import source_row
    row=normalize(source_row())
    for changes in ({'plan_id':'2'},{'name':'不同内容'}):
        with pytest.raises(ValueError,match='完整集合'):
            live.equal_rows([row],[{**row,**changes}])


async def test_cancel_restores_hooks_and_network_context(capacity):
    live=importlib.import_module('repurchase_verification')
    http=SimpleNamespace(request=AsyncMock())
    ingest=SimpleNamespace(publish_page=AsyncMock())
    c=SimpleNamespace(http=http,ingest=ingest,checkpoint_revision=AsyncMock(return_value=0),execute=AsyncMock(side_effect=asyncio.CancelledError()))
    registry={'collector.eastmoney_repurchase':c,'repurchases.query':Mock()}
    manager=SimpleNamespace(start=AsyncMock(),registry=SimpleNamespace(get=registry.__getitem__))
    before=http.request,ingest.publish_page,live.USE_PROXY.get(),live.PROXY_FALLBACK.get(),live.ROUTE_COUNTS.get()
    with pytest.raises(asyncio.CancelledError):
        await live.verify_scope(manager,{},SimpleNamespace(proxy_only=True),dict(results={}))
    assert before==(http.request,ingest.publish_page,live.USE_PROXY.get(),live.PROXY_FALLBACK.get(),live.ROUTE_COUNTS.get())


def test_old_or_failed_source_proof_rejected_before_resources(capacity,tmp_path):
    path=tmp_path/'proof.json'
    for proof in ({'first':{}},{'subject':'repurchases','mode':'verification','source_sha256':'old'},
        {'subject':'repurchases','mode':'verification','source_sha256':capacity.source_digest(capacity.project_root()),'passed':False}):
        path.write_text(json.dumps(proof),encoding='utf8')
        with pytest.raises(ValueError):
            capacity.source_proof(path)


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION')!='1',reason='explicit owned SQL opt-in')
async def test_actual_owned_guard_full_pipeline_and_cleanup(capacity):
    from source_test_storage import read_server_uuid, test_settings
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.test_repurchases import feed, source_row

    cfg=load_config()
    settings=json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf8'))
    storage=capacity.RepurchaseCapacityStorage(test_settings(settings),cfg['redis'],uuid4().hex,token_hex(32),read_server_uuid(cfg['mysql']))
    manager=None
    report=dict(cleanup={},errors=[])
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([],[])
        private=copy.deepcopy(cfg)
        private['mysql'],private['redis']['namespace']=storage.settings,storage.namespace
        manager=build_manager(private)
        await manager.start('infra.http')
        http=manager.registry.get('http.fetch')
        async def response(*args,**kwargs):
            return httpx.Response(200,json=feed([source_row()]),request=httpx.Request('GET',args[1]))
        http.request=AsyncMock(side_effect=response)
        await manager.start('pipeline.archive')
        live=importlib.import_module('repurchase_verification')
        result=dict(results={})
        await live.verify_scope(manager,{},SimpleNamespace(proxy_only=False),result)
        value=result['results']['eastmoney-repurchases']
        assert value['pipeline_verified'] and value['acceptance_complete'] and value['pending_stream']==0
        assert not value['strict_proxy_verified']
        mysql=manager.registry.get('mysql.store')
        def inspect():
            with mysql.read_engine.connect() as conn:
                storage.explain_sql.add('EXPLAIN SELECT * FROM stock_repurchase_plan LIMIT 1')
                assert conn.exec_driver_sql('EXPLAIN SELECT * FROM stock_repurchase_plan LIMIT 1').first()
                for sql in ('SELECT * FROM empire.stock','ANALYZE TABLE stock'):
                    with pytest.raises(ValueError):
                        conn.exec_driver_sql(sql)
        await mysql.read(inspect)
    finally:
        await finish(manager,storage,None,report,Redactor([settings.get('password'),storage.owner]))
    assert not report['errors'] and all(report['cleanup'][k] for k in ('shutdown','sql','redis','sql_lock','connections'))
    assert report['remaining']==dict(sql=False,redis=False)
