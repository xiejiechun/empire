"""Actual TDX name-column semantics, complete-set failures and public lifecycle boundaries."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.contracts.name_changes import (
    MARKETS,
    SCHEMA_VERSION,
    identity,
    pack_rows,
    unpack_rows,
    validate_rows,
)
from empire.plugins.collectors.tdx_name_changes import NameChangeCollector
from empire.plugins.collectors.tdx_name_source import COLUMN_SETS, parse
from empire.plugins.datasets.name_changes import NameDataset
from tests.prefetch_source import prefetch_http


def source(kind='security', missing=False):
    records = [dict(code='000001 ', sc=0, rq=20200102 if kind == 'company' else '20200102',
                    prename=None if missing else '原名称', lastname='新名称', name='当前名称',
                    zjhhy='行业', tdxhy='行业', zqlx='A股'),
               dict(code='600000', sc=1, rq=20210102 if kind == 'company' else '20210102',
                    prename='旧名称', lastname='现名称', name='当前名称', zjhhy='行业', tdxhy='行业', zqlx='A股')]
    rows = [[r[k] for k in COLUMN_SETS[kind]] for r in records]
    return {'ErrorCode': 0, 'ResultSets': [dict(ColName=COLUMN_SETS[kind], Count=len(rows), Content=rows),
            dict(ColName=['page'], Count=1, Content=[[1]]), dict(ColName=['count'], Count=1, Content=[[len(rows)]])]}


@pytest.mark.parametrize('kind', ['company', 'security'])
def test_complete_source_null_and_code_trim(kind):
    groups, count = parse(kind, source(kind, missing=True), '2026-10-05')
    assert count == 2 and len(groups['SZ']) == 1 and groups['BJ'] == []
    assert groups['SZ'][0] == ['000001.SZ', '2020-01-02', None, '新名称', 1, '行业', '行业']


@pytest.mark.parametrize('fault', ['count', 'page', 'duplicate', 'date', 'market', 'type', 'long', 'nonstock'])
def test_protocol_faults_and_same_count_wrong_set(fault):
    data = source()
    result = data['ResultSets'][0]
    row = result['Content'][0]
    col = result['ColName']
    if fault == 'count':
        data['ResultSets'][2]['Content'] = [[3]]
    elif fault == 'page':
        data['ResultSets'][1]['Content'] = [[2]]
    elif fault == 'duplicate':
        result['Content'][1] = list(row)
    else:
        key, value = {'date': ('rq', '20300101'), 'market': ('sc', 9),
                      'type': ('prename', 123), 'long': ('lastname', '名' * 201),
                      'nonstock': ('zqlx', 'B股')}[fault]
        row[col.index(key)] = value
    with pytest.raises((ValueError, TypeError)):
        parse('security', data, '2026-10-05')


def test_company_parallel_and_identical_source_occurrences():
    data = source('company')
    rows = data['ResultSets'][0]['Content']
    rows.append(list(rows[0]))
    parallel = list(rows[0])
    parallel[COLUMN_SETS['company'].index('lastname')] = '并列名称'
    rows.append(parallel)
    data['ResultSets'][0]['Count'] = 4
    data['ResultSets'][2]['Content'] = [[4]]
    groups, count = parse('company', data, '2026-10-05')
    assert count == 4 and len(groups['SZ']) == 2 and sum(r[4] for r in groups['SZ']) == 3
    assert len({identity(r) for r in groups['SZ']}) == 2


async def test_normal_request_once_atomic_publish_no_intermediate_archive_wait():
    c = NameChangeCollector('security')
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=source())), response_policy=lambda _: None)
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision': 0, 'cursor': {}}),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(side_effect=lambda ev, **kw: {'revision': 1, 'cursor': kw['cursor']}),
        advance_checkpoint=AsyncMock())
    async def confirm(*args):
        assert c.ingest.publish_page.await_count == 1
        assert len(c.ingest.publish_page.call_args.args[0]) == 3
        return {'status': 'complete'}
    c.confirmation = SimpleNamespace(page_status=confirm)
    result = await c.execute()
    assert c.http.request.await_count == 1 and result['collected'] == 2
    assert len(json.dumps(result).encode()) < 1024
    assert c.http.request.call_args.kwargs['project_id'] == c.project_id
    assert c.http.request.call_args.kwargs['allowed_domains'] == ('tdx.com.cn',)


async def test_bad_source_never_publishes_or_advances():
    c = NameChangeCollector('security')
    bad = source()
    bad['ResultSets'][0]['Content'][1] = copy.deepcopy(bad['ResultSets'][0]['Content'][0])
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=bad)), response_policy=lambda _: None)
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision': 0, 'cursor': {}}),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(), advance_checkpoint=AsyncMock())
    with pytest.raises(ValueError):
        await c.execute()
    assert not c.ingest.publish_page.called and not c.ingest.advance_checkpoint.called
    assert c.records.add_error.await_count == 1


def test_registration_defaults_schema_and_independence():
    from empire.core.config import load_config
    manager = build_manager(load_config('config/app.example.toml'))
    control = manager.entries['collection.control'].plugin
    for kind in ('company', 'security'):
        c = manager.entries['collector.tdx_' + kind + '_renames'].plugin
        task = control.definitions[c.project_id]
        assert task.default_schedule.mode == 'daily' and task.default_schedule.daily_time == '18:00'
        assert not task.parallel_downloads
        mapping = NameDataset(kind)
        assert manager.entries['dataset.astock'].plugin.namespaces[mapping.FINGERPRINT_NAMESPACE].projects == {c.job_key: c.project_id}
        assert manager.entries['ui.names_' + kind].plugin.create_pages()[0].catalogued


def test_capacity_boundary_and_order():
    rows = [['000001.SZ', '2020-01-01', '旧', '新', 30000, None, None]]
    with pytest.raises(ValueError):
        validate_rows('company', 'SZ', rows)
    with pytest.raises(ValueError):
        validate_rows('security', 'SH', rows)
    assert MARKETS == ('SH', 'SZ', 'BJ')


def test_scoped_capacity_binding_does_not_ignore_business_ddl_changes():
    import hashlib

    from scripts.verify_database_design import verify_scoped_ddl
    measured = 'CREATE TABLE IF NOT EXISTS events (id INT NOT NULL);'
    evidence = {'ddl_scopes': {'events': hashlib.sha256(measured.encode()).hexdigest()}}
    verify_scoped_ddl(evidence, measured + '\nCREATE TABLE IF NOT EXISTS unrelated (id INT);', ['events'])
    with pytest.raises(ValueError, match='重新测量'):
        verify_scoped_ddl(evidence, measured.replace('INT NOT NULL', 'BIGINT NOT NULL'), ['events'])
    with pytest.raises(ValueError):
        verify_scoped_ddl({}, measured, ['events'])


def test_ui_lazy_independence_draft_and_missing_name_display(monkeypatch):
    import concurrent.futures

    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.name_changes import NamePage, NameUiPlugin
    app = QApplication.instance() or QApplication([])
    queries = []
    future = concurrent.futures.Future()
    future.set_result(dict(rows=[dict(record_key='a' * 64, unified_code='000001.SZ',
        event_date='2020-01-01', old_name=None, new_name='新名', source_occurrences=1, csrc_industry='批发业', tdx_industry='其他电子')], next=None))
    runtime = SimpleNamespace(invoke=lambda *args: queries.append(args) or future)
    shell = SimpleNamespace(runtime=runtime, cfg={}, shutting_down=False)
    ui = NameUiPlugin('security')
    pages = ui.create_pages()
    assert pages[0].id == 'names_security' and not queries
    page = NamePage(shell, 'security')
    page.show()
    app.processEvents()
    page.tick()
    page.code.setText('600000')  # An unsubmitted edit must survive refresh completion.
    page.tick()
    assert page.code.text() == '600000' and page.table.item(0, 2).text() == ''
    assert queries[0][0] == 'names.security.query'
    page.next_cursor = ['2020-01-01', '000001.SZ', 'a' * 64]
    page.next.setEnabled(True)
    page.find()
    assert page.next_cursor is None and not page.next.isEnabled() and not page.previous.isEnabled()
    state = page.save_ui_state()
    page.close()
    other = NamePage(shell, 'company')
    other.restore_ui_state(state)
    assert other.code.text() == '600000' and other.kind == 'company'
    other.close()
    page.deleteLater()
    other.deleteLater()


def test_midnight_beijing_request_scope_and_empty_markets():
    from datetime import UTC, datetime

    from empire.contracts.data import make_envelope
    e = make_envelope(source='tdx', dataset='names.security.market', business_key='BJ',
        job_key='tdx-security-renames-v1', run_id='test', batch_id='test',
        schema_version=SCHEMA_VERSION, payload=dict(page=3, market='BJ', through='2026-10-05', **pack_rows([]), source_count=0))
    e = e.model_copy(update={'observed_at': datetime(2026, 10, 4, 16, 5, tzinfo=UTC)})
    assert NameDataset('security').normalize(e)['row_count'] == 0


def test_old_business_migration_never_claims_new_name_table():
    from scripts.business_migration_inventory import NEW, OLD
    assert 'security_name_change' not in OLD and 'security_name_change' not in NEW


def test_industry_dictionary_roundtrip_and_conflicting_source():
    groups, _ = parse('company', source('company'), '2026-10-05')
    rows = groups['SZ']
    packed = pack_rows(rows)
    assert unpack_rows(**packed) == rows
    assert identity(rows[0]) == identity(rows[0][:5] + ['其他行业', '其他标签'])
    for invalid in ({'rows':packed['rows'], 'industries':[]},
                    {'rows':[rows[0][:4]+[True]], 'industries':packed['industries']},
                    {'rows':packed['rows'], 'industries':packed['industries']*2}):
        with pytest.raises(ValueError):
            unpack_rows(**invalid)
    data = source('company')
    duplicate = list(data['ResultSets'][0]['Content'][0])
    duplicate[COLUMN_SETS['company'].index('tdxhy')] = '冲突行业'
    data['ResultSets'][0]['Content'].append(duplicate)
    data['ResultSets'][0]['Count'] = 3
    data['ResultSets'][2]['Content'] = [[3]]
    with pytest.raises(ValueError, match='行业冲突'):
        parse('company', data, '2026-10-05')


@pytest.mark.parametrize('value', [123, '', '名'*201])
def test_industry_invalid_value_rejected(value):
    data = source()
    data['ResultSets'][0]['Content'][0][COLUMN_SETS['security'].index('zjhhy')] = value
    with pytest.raises(ValueError):
        parse('security', data, '2026-10-05')
