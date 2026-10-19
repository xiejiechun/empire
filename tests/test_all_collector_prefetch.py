"""Real source adapters: speculative downloads, ordered proofs, cancellation and budgets."""
import asyncio
import copy
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.features.financial_statements.collector import ThsStatementCollector
from empire.plugins.collectors.ths_listings import ThsListingCollector
from tests.capital_samples import STOCK, issue_detail
from tests.capital_samples import source as capital_source
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher, configured
from tests.test_cninfo_calendar import collector as calendar
from tests.test_cninfo_calendar import response as month_response
from tests.test_listing_status import collector as listing_status
from tests.test_listing_status import source as listing_source
from tests.test_tdx_suspensions import collector as suspensions
from tests.test_tdx_suspensions import response as day_response
from tests.test_ths_industries import collector as industry_fixture
from tests.test_ths_industries import member_page
from tests.test_ths_listings import source as listing_details
from tests.test_ths_statements import source as financial_source

FAMILIES = ['balance', 'income', 'cashflow', 'listings', 'industries', 'calendar',
            'listing_status', 'suspensions', 'dividends', 'additional_issues']


def adapter(family):
    stocks = [{**STOCK, 'code': f'68811{i}'} for i in range(3)]
    if family in ('balance', 'income', 'cashflow', 'listings'):
        c = ThsListingCollector() if family == 'listings' else ThsStatementCollector(family)
        c.ingest = Publisher()
        c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
        c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
        c.query = SimpleNamespace(securities=AsyncMock(return_value=stocks),
                                  plan=AsyncMock(return_value=(stocks, set(), {})))
        c.session = SimpleNamespace(headers=lambda _: {})
        body = listing_details() if family == 'listings' else financial_source(family)
        def reply(method, url, kw):
            index = next(i for i, stock in enumerate(stocks) if stock['code'] in url)
            return index, httpx.Response(200, json=body)
    elif family == 'industries':
        c = industry_fixture.__wrapped__()
        c.ingest = Publisher()
        c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
        codes = ['881155', '881156', '881157']
        catalogue = '<html><div class="cate_inner">' + ''.join(
            f'<a href="http://q.10jqka.com.cn/thshy/detail/code/{code}/">行业{i}</a>'
            for i, code in enumerate(codes)) + '</div></html>'
        def reply(method, url, kw):
            if url.endswith('/thshy/'):
                return None, httpx.Response(200, content=catalogue.encode('gb18030'))
            index = next(i for i, code in enumerate(codes) if code in url)
            return index, httpx.Response(200, content=member_page(
                codes=(f'00000{index + 1}',), industry=codes[index]).encode('gb18030'))
    elif family == 'calendar':
        c = calendar()
        c.query.plan.return_value['months'] = ['2026-09', '2026-10', '2026-11']
        c.query.plan.return_value['expected_count'] = 91
        def reply(method, url, kw):
            month = kw['params']['month']
            return int(month[-2:]) - 9, month_response(month)
    elif family == 'listing_status':
        c = listing_status(date(1991, 1, 3))
        c.query.plan.return_value = ['1991-01']
        def reply(method, url, kw):
            day = json.loads(kw['content'])['Params'][2]
            return int(day[-2:]) - 1, httpx.Response(200, json=listing_source(day, []))
    elif family == 'suspensions':
        c = suspensions()
        c.query.plan.return_value.update(start_date='2026-09-24', end_date='2026-09-26')
        def reply(method, url, kw):
            day = json.loads(kw['content'])['Params'][2]
            return int(day[-2:]) - 24, day_response(day, 1, [], count=0)
    else:
        from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
        from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
        c, _ = configured(TdxDividendsCollector if family == 'dividends' else TdxAdditionalIssuesCollector)
        c.query.securities.return_value = stocks
        c.query.dividend_history_proofs.return_value = {
            'SH:' + s['code']: '2026-01-01T00:00:00+00:00' for s in stocks}
        bodies = [capital_source('additional_issues', code=s['code']) for s in stocks]
        for i, body in enumerate(bodies):
            body['ResultSets'][0]['Content'][0][15] = 1001 + i
        all_rows = [b['ResultSets'][0]['Content'][0] for b in bodies]
        full = capital_source('additional_issues', rows=all_rows, total=3)
        def reply(method, url, kw):
            params = json.loads(kw['content'])['Params']
            if family == 'dividends':
                index = ['2025-06-30', '2025-09-30', '2025-12-31'].index(params[2])
                body = capital_source('dividends')
                body['ResultSets'][1]['Content'][0][-1] = params[2]
                return index, httpx.Response(200, json=body)
            if not url.endswith('_zfmx'):
                return None, httpx.Response(200, json=full)
            index = int(params[0]) - 1001
            return index, httpx.Response(200, json=issue_detail(bodies[index]))
    return c, reply


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mode', ['success', 'bad_first', 'cancel'])
async def test_real_adapters_prefetch_without_crossing_unvalidated_frontier(family, mode, monkeypatch):
    c, reply = adapter(family)
    if family == 'dividends':
        monkeypatch.setattr('empire.plugins.collectors.tdx_dividend_periods.report_periods',
            AsyncMock(return_value=['2025-06-30', '2025-09-30', '2025-12-31']))
    validation = {
        'balance': ('ths_statements', 'parse'), 'income': ('ths_statements', 'parse'),
        'cashflow': ('ths_statements', 'parse'), 'listings': ('ths_listings', 'parse'),
        'industries': ('ths_industries', 'parse_members'), 'calendar': ('cninfo_calendar', 'parse_month'),
        'listing_status': ('tdx_listing_status', 'parse'), 'suspensions': ('tdx_suspensions', 'parse_page'),
        'dividends': ('tdx_capital_source', 'parse'), 'additional_issues': ('tdx_issue_detail', 'parse'),
    }
    import importlib
    module, attribute = validation[family]
    module = importlib.import_module({
        'ths_statements': 'empire.features.financial_statements.collector',
        'ths_industries': 'empire.features.industries.collector',
    }.get(module, 'empire.plugins.collectors.' + module))
    original_parse = getattr(module, attribute)
    validations = []
    def parse(*args, **kwargs):
        validations.append(args)
        return original_parse(*args, **kwargs)
    monkeypatch.setattr(module, attribute, parse)
    release = asyncio.Event()
    started, completed, responses = [], [], []
    original_state = copy.deepcopy(await c.ingest.checkpoint(c.job_key))
    async def request(method, url, **kw):
        index, response = reply(method, url, kw)
        assert kw['project_id'] == c.project_id
        responses.append(response)
        if index is None:
            return response
        assert kw['reservation'] is not None and not kw['reservation'].released
        started.append(index)
        if index == 0:
            try:
                await release.wait()
            except asyncio.CancelledError:
                response.close()
                raise
            if mode == 'bad_first':
                response.close()
                response = httpx.Response(200, request=httpx.Request(method, url), json={})
                responses.append(response)
        completed.append(index)
        return response
    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    c.http.parallelism.return_value = 3
    task = asyncio.create_task(c.execute())
    try:
        await until(lambda: 1 in completed and 2 in completed)
        assert started == [0, 1, 2] and completed == [1, 2]
        assert validations == []
        if family == 'listing_status':
            checkpoint = await c.ingest.checkpoint(c.job_key)
            assert checkpoint['cursor']['pages'] == 0 and not c.ingest.events
        else:
            assert await c.ingest.checkpoint(c.job_key) == original_state
        assert c.confirmation.page_status.await_count == 0
        assert c.http.buffer_budget.used == 3 * c.http.response_policy(
            'calendar' if family == 'calendar' else 'generic').reservation_bytes
        if mode == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            if mode == 'bad_first':
                with pytest.raises((ValueError, KeyError, TypeError)):
                    await task
                cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
                assert cursor.get('index', 0) == cursor.get('pages', 0) == 0
                c.confirmation.page_status.assert_not_awaited()
            else:
                await task
                assert completed == [1, 2, 0]
                assert len(validations) == 3
                assert (await c.ingest.checkpoint(c.job_key))['cursor']['phase'] == 'complete'
                c.confirmation.page_status.assert_awaited_once()
        assert c.http.buffer_budget.used == c.http.buffer_budget.waiting == 0
        assert all(r.is_closed for r in responses)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_every_registered_task_declares_its_actual_independent_download_capability():
    manager = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    tasks = manager.entries['collection.control'].plugin.definitions
    serial = {'eastmoney-repurchases', 'sina-news', 'ths-stocks', 'tdx-company-renames', 'tdx-security-renames', 'tdx-rights-issues', 'tdx-st-implementation', 'tdx-st-removal'}
    assert len(tasks) == 45
    assert tasks['ths-capital'].parallel_downloads
    assert tasks['tdx-shareholder-changes'].parallel_downloads
    assert 'ths-holders' in tasks
    assert {t.id for t in tasks.values() if not t.parallel_downloads} == serial
