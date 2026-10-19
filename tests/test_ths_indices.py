import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.features.indices.collector import ThsIndexCollector
from empire.features.indices.contract import BASE, JOB, member_identity, members_url
from empire.features.indices.dataset import fingerprint_plan, normalize
from empire.features.indices.source import parse_catalog, parse_members
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher

CATALOG = [dict(code='1A0001', name='上证指数', group='重要'), dict(code='399003', name='成份Ｂ指', group='其他')]


def catalog_html(rows=CATALOG):
    return '<html><div class="cate_inner">' + ''.join(
        '<div class="cate_group"><span class="cate_letter">' + r['group'] + '</span><div class="cate_items">'
        + f'<a href="http://q.10jqka.com.cn/zs/detail/code/{r["code"]}/">{r["name"]}</a></div></div>' for r in rows) + '</div></html>'


def member_html(code='1A0001', members=('000001', '600000'), available=True):
    body = ''.join('<tr><td>' + str(i + 1) + '</td>' + ''.join(
        f'<td><a href="http://stockpage.10jqka.com.cn/{c}/">{v}</a></td>' for v in (c, '样本证券'))
        + '<td>--</td>' * 11 + '</tr>' for i, c in enumerate(members)) if available else '<tr><td colspan="14">暂无成份股数据</td></tr>'
    return (f'<table class="m-table"><tbody>{body}</tbody></table><div class="m-pager"></div>'
            f'<input id="baseUrl" value="zs/detail"><input id="requestQuery" value="code/{code}">')


def envelope(code='1A0001', members=None, available=True, page=2):
    return make_envelope(source='ths', dataset='index.members', business_key=code, job_key=JOB,
        run_id='test', batch_id='test', payload=dict(page=page, code=code, available=available,
                                                   members=members if members is not None else [['000001', '样本证券'], ['600000', '样本证券']]))


def collector():
    c = ThsIndexCollector()
    c.ingest = Publisher()
    c.session = SimpleNamespace(headers=lambda _: {})
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    def request(method, url, **kw):
        assert kw['allowed_domains'] == ('10jqka.com.cn',) and kw['project_id'] == 'ths-indices'
        body = catalog_html() if url == BASE else member_html(code='399003', members=('200012',)) if '399003' in url else member_html()
        return httpx.Response(200, content=body.encode('gb18030'))
    c.http = prefetch_http(request=AsyncMock(side_effect=request), response_policy=lambda _: None)
    return c


def test_catalog_and_cross_market_member_contract():
    assert parse_catalog(catalog_html()) == CATALOG
    assert parse_members(member_html(), '1A0001')['members'] == [['000001', '样本证券'], ['600000', '样本证券']]
    assert member_identity('200012') == '200012.SZ' and member_identity('900901') == '900901.SH'
    assert member_identity('00700') is None
    assert parse_members(member_html(available=False), '1A0001') == dict(available=False, members=[])
    assert '/page/1/size/10000/' in members_url('1A0001')


@pytest.mark.parametrize('body', [catalog_html([]), catalog_html(CATALOG + CATALOG), catalog_html()[:-7],
                                  catalog_html().replace('1A0001/', '1A0001/evil/')])
def test_invalid_catalog_rejected(body):
    with pytest.raises(ValueError):
        parse_catalog(body)


@pytest.mark.parametrize('body', [member_html(members=('000001', '000001')), member_html(members=('600000', '000001')),
    member_html().replace('<div class="m-pager"></div>', '<div class="m-pager"><a>2</a></div>'),
    member_html().replace('code/1A0001', 'code/399003'), member_html().replace('</tbody>', ''),
    member_html().replace('stockpage.10jqka.com.cn/600000', 'stockpage.10jqka.com.cn/600001'),
    member_html(members=()), '<html>upass.10jqka.com.cn/login</html>',
    member_html(available=False).replace('暂无成份股数据', '未知空结果')])
def test_same_count_duplicate_identity_pagination_and_empty_fail(body):
    with pytest.raises(ValueError):
        parse_members(body, '1A0001')


def test_fingerprint_excludes_batch_page_and_allows_overlapping_members():
    e = envelope()
    assert fingerprint_plan(e, normalize(e)) == fingerprint_plan(e.model_copy(update={'batch_id': 'another'}), normalize(e))
    assert normalize(envelope(code='399003'))['rows'] == normalize(e)['rows']
    with pytest.raises(ValueError):
        normalize(envelope(members=[['000001', '甲'], ['000001', '乙']]))
    assert normalize(envelope(members=[], available=False))['row_count'] == 0


async def test_one_request_per_unit_and_no_archive_wait_between_publications():
    c = collector()
    gate = asyncio.Event()
    async def confirm(*args):
        assert len(c.ingest.events) == 3
        await gate.wait()
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while c.stats['status'] != 'awaiting_archive':
            await asyncio.sleep(0)
    assert c.http.request.await_count == 3 and c.ingest.state['cursor']['next_index'] == 2
    assert not task.done()
    gate.set()
    result = await task
    assert result['phase'] == 'complete' and result['collected'] == 3
    assert [e.raw_payload['page'] for e in c.ingest.events] == [1, 2, 3]


async def test_failure_keeps_frontier_and_resume_skips_published_units():
    c = collector()
    original = c.http.request.side_effect
    def bad(method, url, **kw):
        return httpx.Response(200, content=member_html(code='399003', members=('200012', '200012')).encode('gb18030')) if '399003' in url else original(method, url, **kw)
    c.http.request.side_effect = bad
    with pytest.raises(ValueError):
        await c.execute()
    assert c.ingest.state['cursor']['next_index'] == 1
    assert len(c.ingest.events) == 2
    c.http.request.reset_mock()
    c.http.request.side_effect = original
    await c.execute(fresh=True)
    assert c.http.request.await_count == 1
    assert '399003' in c.http.request.call_args.args[1]


async def test_cancel_after_all_queue_resumes_without_network():
    c = collector()
    gate = asyncio.Event()
    async def waiting(*args):
        await gate.wait()
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = waiting
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while c.stats['status'] != 'awaiting_archive':
            await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    c.http.request.reset_mock()
    c.confirmation.page_status.side_effect = None
    c.confirmation.page_status.return_value = {'status': 'complete'}
    await c.execute(fresh=True)
    assert not c.http.request.called


def test_plugin_registration_defaults_and_lazy_page():
    m = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    task = m.entries['collection.control'].plugin.definitions['ths-indices']
    assert task.parallel_downloads and task.default_schedule.mode == 'daily'
    page = m.entries['ui.indices'].plugin.create_pages()[0]
    assert page.catalogued and page.management.context.task_id == 'ths-indices'


async def test_maximum_catalog_keeps_public_checkpoint_bounded():
    c = collector()
    class PublicPublisher(Publisher):
        async def publish_page(self, envelopes, *, expected_revision, cursor, **kw):
            assert expected_revision == self.state['revision']
            self.events.extend(envelopes)
            self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
            return copy.deepcopy(self.state)
    c.ingest = PublicPublisher()
    catalog = [dict(code=f'{n:06d}', name='长名称' * 25, group='其他') for n in range(1000)]
    async def fetch(url, parser, **kw):
        if url == BASE:
            return catalog
        raise RuntimeError('stop after directory')
    c.fetch = fetch
    c.http.request.side_effect = RuntimeError('stop after directory')
    with pytest.raises(RuntimeError):
        await c.execute()
    cursor = c.ingest.state['cursor']
    assert len(cursor['codes']) == 1000 and 'catalog' not in cursor
    assert len(json.dumps(cursor, ensure_ascii=False).encode()) < 16384


@pytest.mark.parametrize('mode', ['success', 'bad_first', 'cancel'])
async def test_parallel_member_frontier_and_budget_cleanup(mode):
    c = collector()
    catalog = [dict(code=f'39900{n}', name=f'指数{n}', group='其他') for n in range(3)]
    release = asyncio.Event()
    started, completed, responses = [], [], []
    async def request(method, url, **kw):
        if url == BASE:
            return httpx.Response(200, content=catalog_html(catalog).encode('gb18030'))
        index = next(n for n, row in enumerate(catalog) if row['code'] in url)
        started.append(index)
        if index == 0:
            await release.wait()
        response = httpx.Response(200, content=('{}' if mode == 'bad_first' and index == 0 else
            member_html(code=catalog[index]['code'])).encode('gb18030'))
        responses.append(response)
        completed.append(index)
        return response
    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    c.http.parallelism.return_value = 3
    # Catalogue contains 3 short identities, within this test publisher's stricter bound.
    task = asyncio.create_task(c.execute())
    try:
        async with asyncio.timeout(3):
            while 1 not in completed or 2 not in completed:
                await asyncio.sleep(0)
        assert started == [0, 1, 2] and completed == [1, 2]
        assert c.ingest.state['cursor']['next_index'] == 0 and len(c.ingest.events) == 1
        assert c.http.buffer_budget.used == 3 * c.http.response_policy('generic').reservation_bytes
        if mode == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            if mode == 'bad_first':
                with pytest.raises(ValueError):
                    await task
                assert c.ingest.state['cursor']['next_index'] == 0 and len(c.ingest.events) == 1
            else:
                await task
                assert [e.raw_payload['page'] for e in c.ingest.events] == [1, 2, 3, 4]
        assert all(r.is_closed for r in responses)
        assert c.http.buffer_budget.used == c.http.buffer_budget.waiting == 0
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
