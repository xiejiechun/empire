import asyncio
import copy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.contracts.preparation_scope import PreparationScope
from empire.features.industries.collector import ThsIndustryCollector
from empire.features.industries.contract import market
from empire.features.industries.dataset import (
    CONTRACT_VERSION,
    JOB,
    PROJECT,
    digest,
    normalize,
    validate,
)
from empire.features.industries.query import IndustryDataPlugin
from empire.features.industries.source import (
    BASE,
    members_url,
    parse_catalog,
    parse_members,
)
from tests.prefetch_source import prefetch_http

CATALOG = '<html><div class="cate_inner"><a href="http://q.10jqka.com.cn/thshy/detail/code/881155/">银行</a></div></html>'
SNAPSHOT = [dict(code='881155', name='银行', members=[['000001', '平安银行'], ['600000', '浦发银行']])]


def member_page(codes=('000001', '600000'), page=1, pages=1, industry='881155'):
    rows = []
    for index, code in enumerate(codes):
        rows.append('<tr><td>' + str((page - 1) * 20 + index + 1) + '</td>'
            + f'<td><a href="http://stockpage.10jqka.com.cn/{code}/">{code}</a></td>'
            + f'<td><a href="http://stockpage.10jqka.com.cn/{code}">证券{code}</a></td>'
            + '<td>0</td>' * 11 + '</tr>')
    return ('<table class="m-table"><tbody>' + ''.join(rows) + '</tbody></table>'
            + f'<input id="requestQuery" value="code/{industry}">'
            + f'<span class="page_info">{page}/{pages}</span>')


def response(url):
    return httpx.Response(200, content=(CATALOG if url == BASE else member_page()).encode('gbk'))


def test_catalog_and_unique_code_order_protocol():
    assert parse_catalog(CATALOG) == [{'code': '881155', 'name': '银行'}]
    codes = [f'000{i:03d}' for i in range(1, 277)]
    members = parse_members(member_page(codes), '881155')
    assert [m[0] for m in members] == codes
    assert '/field/code/order/asc/page/1/size/1000/' in members_url('881155')


@pytest.mark.parametrize('source', ['', CATALOG[:-7], CATALOG.replace('</div>', CATALOG[6:-7] + '</div>'),
                                  CATALOG.replace('/881155/', '/bad/')])
def test_invalid_catalog(source):
    with pytest.raises(ValueError):
        parse_catalog(source)


@pytest.mark.parametrize('source', [
    '<script>challenge</script>',
    member_page([], 1, 1),
    member_page(['000001', '000001']),
    member_page(['600000', '000001']),
    member_page(['000001'], 1, 2),
    member_page(['600000'], 2, 3),
    member_page(['600000'], 2, 2),
    member_page(industry='881156'),
    member_page().replace('<td>1</td>', '<td>2</td>'),
    member_page().replace('/000001/', '/000002/'),
    member_page().replace('</tbody>', ''),
])
def test_incomplete_or_same_count_different_members_rejected(source):
    with pytest.raises(ValueError):
        parse_members(source, '881155')


def test_wire_and_cross_industry_identity():
    envelope = make_envelope(source='ths', dataset='industry.snapshot', business_key='current',
        job_key=JOB, run_id='test', batch_id='test', payload={'page': 1, 'industries': SNAPSHOT})
    assert normalize(envelope)['row_count'] == 2
    for bad in ([], [*SNAPSHOT, dict(code='881156', name='保险', members=SNAPSHOT[0]['members'])],
                [dict(code='881155', name='银行', members=[['000001', '甲'], ['000001', '乙']])]):
        with pytest.raises(ValueError):
            validate(bad)


def test_market_identity_does_not_label_shanghai_b_share_as_beijing():
    assert market('920001') == 'BJ' and market('430001') == 'BJ'
    assert market('600000') == 'SH' and market('000001') == 'SZ'
    with pytest.raises(ValueError):
        market('900901')


@pytest.fixture
def collector():
    c = ThsIndustryCollector()
    c.session = SimpleNamespace(headers=lambda _: {'Cookie': 'v=test'})
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw: response(url)),
                             response_policy=lambda _: None)
    c.records = SimpleNamespace(sanitize_text=str, error=AsyncMock())
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision': 0, 'cursor': {}}),
                              advance_checkpoint=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    return c


async def test_only_complete_unit_queued_before_archive_wait(collector, monkeypatch):
    module = 'empire.features.industries.collector.'
    monkeypatch.setattr(module + 'wait_for_capacity', AsyncMock())
    published = []
    async def publish(ingest, stats, envelopes, **kw):
        assert collector.http.request.await_count == 2
        published.extend(envelopes)
        return {'revision': 1, 'cursor': kw['cursor']}
    monkeypatch.setattr(module + 'publish_with_capacity', publish)
    result = await collector.execute()
    assert result['phase'] == 'complete' and len(published) == 1
    assert collector.http.request.await_count == 2
    assert published[0].observed_at <= datetime.now(UTC)
    assert collector.confirmation.page_status.await_count == 1


@pytest.mark.parametrize('error', [ValueError('bad page'), asyncio.CancelledError()])
async def test_failure_or_cancel_never_advances_or_publishes(collector, monkeypatch, error):
    module = 'empire.features.industries.collector.'
    monkeypatch.setattr(module + 'wait_for_capacity', AsyncMock())
    monkeypatch.setattr(module + 'record_error_safely', AsyncMock())
    publish = AsyncMock()
    monkeypatch.setattr(module + 'publish_with_capacity', publish)
    collector.http.request.side_effect = [response(BASE), error]
    with pytest.raises(type(error)):
        await collector.execute()
    assert not publish.called and not collector.ingest.advance_checkpoint.called


async def test_resume_queued_round_does_not_redownload_even_fresh(collector):
    collector.ingest.checkpoint.return_value = {'revision': 2, 'cursor': dict(
        phase='awaiting_archive', batch_id='batch', collected=2, pages=1)}
    result = await collector.execute(fresh=True)
    assert result['phase'] == 'complete' and not collector.http.request.called


async def test_preparation_content_proof_scope_and_historical_limit():
    query = IndustryDataPlugin()
    state = dict(contract_version=CONTRACT_VERSION, digest=digest(SNAPSHOT), industry_count=1, member_count=2,
                 observed_at=datetime.now(UTC).isoformat(timespec='microseconds'))
    checks = await query.audit(SNAPSHOT, state, PreparationScope())
    assert isinstance(checks, tuple)
    assert all(c.status == 'pass' for c in checks)
    checks = await query.audit(SNAPSHOT, state, PreparationScope(purpose='historical_signal', codes=('600001',)))
    assert {c.criterion for c in checks if c.status == 'fail'} == {'coverage', 'temporal'}
    wrong = copy.deepcopy(SNAPSHOT)
    wrong[0]['members'][1][0] = '600001'
    assert next(c for c in await query.audit(wrong, state, PreparationScope()) if c.criterion == 'coverage').status == 'fail'
    assert all(c.status == 'fail' for c in await query.audit([], {}, PreparationScope()) if c.criterion != 'temporal')
    malformed = {**state, 'observed_at': '2026-01-01'}
    invalid = await query.audit(SNAPSHOT, malformed, PreparationScope())
    assert {c.criterion for c in invalid if c.status == 'fail'} == {'coverage', 'freshness'}
    old = await query.audit(SNAPSHOT, {**state, 'contract_version': 1}, PreparationScope())
    assert next(c for c in old if c.criterion == 'coverage').status == 'fail'


async def test_dashboard_accepts_formal_industry_evidence_contract():
    from empire.contracts.preparation_catalog import BY_ID
    from empire.plugins.data.preparation import PreparationPlugin

    query = IndustryDataPlugin()
    state = dict(contract_version=CONTRACT_VERSION, digest=digest(SNAPSHOT), industry_count=1, member_count=2,
                 observed_at=datetime.now(UTC).isoformat(timespec='microseconds'))
    query.mysql = SimpleNamespace(read=AsyncMock(return_value=(SNAPSHOT, state)))
    contribution = query.preparation[0]
    dashboard = PreparationPlugin([contribution])
    dashboard.context = SimpleNamespace(optional=lambda capability: query if capability == 'industries.query' else None)
    report = await dashboard.provider_report(BY_ID['industries'], contribution, {}, '')
    assert all(c['status'] == 'pass' for c in report['checks'] if c['phase'] == '数据')


def test_registered_project_and_no_direct_only_default():
    manager = build_manager(dict(redis={}, mysql={}, rate_groups={}, archive={}, ingest={}))
    task = manager.entries['collection.control'].plugin.definitions[PROJECT]
    assert task.category == '证券基础' and task.source_name == '同花顺'
    catalog = manager.entries['dataset.astock'].plugin
    assert catalog.datasets['industry.snapshot'].projects == {JOB: PROJECT}


def test_local_verification_uses_bundled_script_without_network():
    import subprocess
    import sys
    code = ('from PySide6.QtCore import QCoreApplication; '
            'from empire.plugins.collectors.ths_session import ThsSession; '
            'app=QCoreApplication([]); h=ThsSession().headers("https://q.10jqka.com.cn/thshy/"); '
            'assert len(h["Cookie"])==62; print("PASS")')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PASS'


def test_single_page_source_uses_explicit_empty_pager():
    source = member_page().replace('<span class="page_info">1/1</span>', '<div class="m-pager" id="m-page"></div>')
    assert len(parse_members(source, '881155')) == 2
    with pytest.raises(ValueError):
        parse_members(source.replace('<div class="m-pager" id="m-page"></div>', ''), '881155')
    with pytest.raises(ValueError):
        parse_members(source.replace('id="m-page"></div>', 'id="m-page"><a>2</a></div>'), '881155')


def test_login_response_is_not_empty_industry_or_retryable_page():
    with pytest.raises(ValueError, match='同花顺要求登录'):
        parse_members('<script>location.href="//upass.10jqka.com.cn/login"</script>', '881109')


@pytest.mark.parametrize('count', [1000, 1001])
def test_size_limit_response_cannot_claim_completeness(count):
    codes = [f'{i:06d}' for i in range(1, count + 1)]
    with pytest.raises(ValueError, match='上限'):
        parse_members(member_page(codes), '881155')
