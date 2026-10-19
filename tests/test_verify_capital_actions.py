"""Whole-list observation and independently checked issue-detail provenance."""
import copy
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('verify_capital_actions')


def test_downloaded_details_must_match_including_last_available(verifier):
    from empire.features.capital_actions.parser import parse
    from tests.capital_samples import source, with_issue_detail
    rows = parse('additional_issues', source('additional_issues'), 10000)[0]
    with_issue_detail(rows)
    ident = rows[0]['data']['source_id']
    detail = copy.deepcopy(rows[0]['data']['detail'])
    verifier.check_details(rows, [], {ident: detail})
    wrong = copy.deepcopy(rows)
    wrong[0]['data']['detail']['issue_name'] = 'changed'
    with pytest.raises(ValueError, match='本轮来源'):
        verifier.check_details(wrong, [], {ident: detail})
    verifier.check_details(rows, rows, {})
    with pytest.raises(ValueError, match='可复用'):
        verifier.check_details(rows, [], {})


async def test_cancel_restores_source_and_publish_observers(verifier):
    import asyncio
    store = SimpleNamespace(prefix='private')
    mysql = SimpleNamespace(control=AsyncMock())
    collector = SimpleNamespace(job_key='job', stats={}, execute=AsyncMock(side_effect=asyncio.CancelledError()),
                                ingest=SimpleNamespace(publish_page=AsyncMock()))
    resources = {'redis.store': store, 'mysql.store': mysql, 'collector.tdx_rights_issues': collector,
                 'rights_issues.query': object()}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    originals = verifier.lifecycle.complete_response, verifier.issue_prefetch.fetch_detail, collector.ingest.publish_page
    with pytest.raises(asyncio.CancelledError):
        await verifier.scope(manager, SimpleNamespace(kind='rights_issues', proxy_only=False), dict(results={}), {})
    assert originals == (verifier.lifecycle.complete_response, verifier.issue_prefetch.fetch_detail,
                         collector.ingest.publish_page)


@pytest.mark.parametrize('kind', ['rights_issues', 'additional_issues'])
@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL opt-in')
async def test_actual_guarded_list_pipeline(verifier, kind):
    import json
    from secrets import token_hex
    from uuid import uuid4

    import httpx
    from source_test_storage import PrivateStorage, read_server_uuid
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.capital_samples import issue_detail, source
    from tests.prefetch_source import prefetch_http

    cfg = load_config()
    test = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = PrivateStorage(test, cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager = None
    cleanup = dict(cleanup={}, errors=[])
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'], test_cfg['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(test_cfg)
        await manager.start('pipeline.archive')
        await manager.start('collector.tdx_' + kind)
        collector = manager.registry.get('collector.tdx_' + kind)
        collector.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200,
            json=issue_detail() if a[1].endswith('tdxsj_xgzx_zfmx') else source(kind))),
            response_policy=lambda profile: profile)
        report = dict(results={})
        await verifier.scope(manager, SimpleNamespace(kind=kind, proxy_only=False), report,
                             dict(rows=[], state=None, setting=None))
        result = report['results'][kind]
        assert result['pipeline_verified'] and result['acceptance_complete']
        assert result['pending'] == 0 and result['source_count'] == 1
        assert result['comparison']['retained_history_count'] == 0
        assert len(result['details']) == (1 if kind == 'additional_issues' else 0)
        assert not result['strict_proxy_verified']
    finally:
        await finish(manager, storage, None, cleanup, Redactor([storage.owner]))
    assert not cleanup['errors'] and all(cleanup['cleanup'].values())
