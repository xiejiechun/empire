"""Whole-set, cancellation and actual owned SQL smoke for unlock validation tools."""
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
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('unlock_capacity')


@pytest.mark.parametrize('family', ['unlocks', 'industries'])
def test_exact_capacity_guard_and_actual_identity(capacity, family):
    storage = capacity.UnlockCapacityStorage(dict(host='test',port=13348,user='test'), {}, 'a'*32, 'b'*64,
                                            'production', protocol=capacity.protocol(family))
    storage.server_uuid='private'
    conn=Mock()
    conn.engine.url.database=storage.database
    raw=conn.connection.cursor.return_value
    raw.fetchone.return_value=('private', storage.database)
    table='restricted_share_unlock' if family=='unlocks' else 'restricted_share_unlock_industry'
    statement='EXPLAIN SELECT * FROM '+table+' LIMIT 1'
    storage.explain_sql={statement}
    for sql in ['ANALYZE TABLE '+table, statement]:
        storage.guard(conn,None,sql,(),None,False)
        for identity in [('production',storage.database),('private','empire')]:
            raw.fetchone.return_value=identity
            with pytest.raises(ValueError,match='实际实例'):
                storage.guard(conn,None,sql,(),None,False)
        raw.fetchone.return_value=('private',storage.database)
    for sql in ['EXPLAIN SELECT * FROM stock', 'ANALYZE TABLE stock', statement+'; DELETE FROM stock']:
        with pytest.raises(ValueError):
            storage.guard(conn,None,sql,(),None,False)
    with pytest.raises(ValueError):
        storage.guard(conn,None,statement,{'unexpected':1},None,False)


def test_equal_count_different_set_or_content_rejected(capacity):
    live=importlib.import_module('unlock_verification')
    for wrong in [[dict(code='B',shares='1')],[dict(code='A',shares='2')]]:
        with pytest.raises(ValueError,match='完整集合内容'):
            live.equal_sets([dict(code='A',shares='1')],wrong)


@pytest.mark.parametrize('family', ['unlocks', 'industries'])
async def test_cancel_restores_instrumentation_and_route_context(capacity,family):
    live=importlib.import_module('unlock_verification')
    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
    http=SimpleNamespace(request=AsyncMock())
    ingest=SimpleNamespace(publish_page=AsyncMock())
    collector=SimpleNamespace(http=http,ingest=ingest,project_id='test',execute=AsyncMock(),
                              checkpoint_revision=AsyncMock(side_effect=asyncio.CancelledError()))
    ident='collector.tdx_unlock_industries' if family=='industries' else 'collector.tdx_unlocks'
    manager=SimpleNamespace(start=AsyncMock(),entries={ident:SimpleNamespace(plugin=collector)},registry=Mock())
    before=(http.request,ingest.publish_page,USE_PROXY.get(),PROXY_FALLBACK.get(),ROUTE_COUNTS.get())
    with pytest.raises(asyncio.CancelledError):
        await live.verify_scope(manager,{},SimpleNamespace(family=family,months=['2020-01-01'],proxy_only=False),dict(results={}))
    assert before==(http.request,ingest.publish_page,USE_PROXY.get(),PROXY_FALLBACK.get(),ROUTE_COUNTS.get())


def test_sample_required_not_stale_or_other_subject(capacity,tmp_path,monkeypatch):
    monkeypatch.setattr(capacity,'project_root',lambda:tmp_path)
    monkeypatch.setattr(capacity,'source_digest',lambda _: 'current')
    with pytest.raises(ValueError,match='必须提供'):
        capacity.load_sample(SimpleNamespace(sample=None),'unlocks')
    path=tmp_path/'bad.json'
    path.write_text(json.dumps(dict(passed=True,pipeline_verified=True,source_sha256='old')))
    with pytest.raises(ValueError,match='源码已改变'):
        capacity.load_sample(SimpleNamespace(sample=str(path)),'unlocks')
    assert capacity.load_sample(SimpleNamespace(sample=None),'industries') is None


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION')!='1',reason='Opt in to owned SQL/Redis')
@pytest.mark.parametrize('family',['unlocks','industries'])
async def test_full_original_capacity_and_fixture_source_pipeline(capacity,family,monkeypatch):
    from source_verification import finish

    from empire.__main__ import acquire_instance_lock
    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.test_tdx_unlock_industries import directory
    from tests.test_tdx_unlock_industries import source as industry_source
    from tests.test_tdx_unlocks import detail, normalized, source
    live=importlib.import_module('unlock_verification')
    cfg=load_config()
    settings=json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf8'))
    storage=capacity.UnlockCapacityStorage(settings,cfg['redis'],uuid4().hex,token_hex(32),
        capacity.read_server_uuid(cfg['mysql']),protocol=capacity.protocol(family))
    manager=lock=None
    report=dict(results={},cleanup={},errors=[])
    try:
        lock=acquire_instance_lock()
        storage.create_sql()
        await storage.create_redis()
        storage.seed([],[])
        parents,children=normalized()
        # Named fixture input, deliberately not a claimed real-source report.
        sample=dict(representative_parent=parents[0],representative_detail=children[0])
        measured=await asyncio.to_thread(capacity.measure,storage,sample)
        assert measured['correctness']['all_units_equal']
        assert measured['correctness']['repeat_business_dml']==0
        assert measured['correctness']['revision_written']==1
        private=copy.deepcopy(cfg)
        private['mysql'],private['redis']['namespace']=storage.settings,storage.namespace
        manager=build_manager(private)
        await manager.start('infra.http')
        http=manager.registry.get('http.fetch')
        async def response(method,url,**kw):
            params=json.loads(kw['content'])['Params']
            if family=='unlocks':
                value=source() if params[0]=='0' else detail()
            else:
                value=directory() if params[0]=='dxfhy' else industry_source(params[0][:4]+'-'+params[0][4:]+'-01')
            return httpx.Response(200,json=value)
        http.request=AsyncMock(side_effect=response)
        # Capacity rows are outside this source scope; stock-specific checks use a source-only code.
        await live.verify_scope(manager,dict(selected=[dict(unified_code='603027.SH')]),
            SimpleNamespace(family=family,months=['2020-01-01'],proxy_only=False),report)
        result=next(iter(report['results'].values()))
        assert result['pipeline_verified'] and result['pending_stream']==0
        assert not result['strict_proxy_verified']  # Fixture bytes never count as real proxy acceptance.
    finally:
        await finish(manager,storage,lock,report,Redactor([storage.owner]))
    assert not report['errors'] and all(report['cleanup'].values())
    assert report['remaining']==dict(sql=False,redis=False)
