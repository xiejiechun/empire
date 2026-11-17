"""Index source contracts, independent task lifecycle and safe empty handling."""
import json
import struct
import zlib
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from empire.contracts.data import make_envelope
from empire.features.yuanhang_indices import catalog_dataset, member_dataset, price_dataset
from empire.features.yuanhang_indices.contract import (
    CATALOG_DATASET,
    MEMBER_DATASET,
    PRICE_DATASET,
    number,
)
from empire.features.yuanhang_indices.member_collector import MemberCollector
from empire.features.yuanhang_indices.members_source import parse_members
from empire.features.yuanhang_indices.native import daily, expand_codes, market_codes, names
from empire.features.yuanhang_indices.price_collector import PriceCollector
from empire.plugins.infra.collection_state_unit import unit_path
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher

CATALOG = [dict(code='1A0001', name='上证指数', native_market='USHI'),
           dict(code='899050', name='北证50', native_market='USTI')]
ROWS = [['2026-11-13', '10', '11', None, '10.5', None, '-1']]


def member_html(code='1A0001', available=True, members=('000001', '600000')):
    rows = ''.join('<tr><td>' + str(i+1) + '</td>' + ''.join(
        f'<td><a href="http://stockpage.10jqka.com.cn/{c}/">{v}</a></td>' for v in (c, '样本证券'))
        + '<td>--</td>' * 11 + '</tr>' for i, c in enumerate(members)) if available else '<tr><td colspan="14">暂无成份股数据</td></tr>'
    return f'<table class="m-table"><tbody>{rows}</tbody></table><div class="m-pager"></div><input id="baseUrl" value="zs/detail"><input id="requestQuery" value="code/{code}">'


def envelope(dataset=MEMBER_DATASET, *, code='1A0001', payload=None):
    if payload is None:
        payload = dict(code=code, available=True, members=[['600000', '样本证券']])
    ident = 'catalog' if dataset == CATALOG_DATASET else code + ':2026' if dataset == PRICE_DATASET else code
    project = {CATALOG_DATASET: 'ths-yuanhang-indices', MEMBER_DATASET: 'ths-yuanhang-index-members', PRICE_DATASET: 'ths-yuanhang-index-prices'}[dataset]
    return make_envelope(source='ths' if dataset == MEMBER_DATASET else 'ths_yuanhang', dataset=dataset,
        business_key=ident, job_key=project+'-v1', batch_id='test', run_id='test', payload=dict(page=1, **payload))


def market_packet(text, instance=1):
    raw = text.encode('gbk')
    plain = struct.pack('<I', len(raw)) + raw
    payload = struct.pack('<I', len(plain)) + zlib.compress(plain)
    return struct.pack('<HiIHiB', 17, instance, 240, 0x0202, len(payload), 1) + payload


def test_all_market_code_segments_and_source_total():
    body = market_packet('[Market_16_16]\nTotalStock=4\nCodeList=1A0001-1A0002\nCodeList_1=1B0012\nCodeList_2=1B0300\n')
    reserved = []
    assert market_codes(body, 'USHI', instance=1, limit=10000, reserve=reserved.append) == ['1A0001', '1A0002', '1B0012', '1B0300']
    assert reserved and expand_codes('399001-399003,980023') == ['399001', '399002', '399003', '980023']
    with pytest.raises(ValueError):
        market_codes(body[:-1], 'USHI', instance=1, limit=10000)
    with pytest.raises(ValueError):
        market_codes(body, 'USHI', instance=2, limit=10000)
    with pytest.raises(ValueError):
        market_codes(body, 'USHI', instance=1, limit=30)
    with pytest.raises(ValueError):
        market_codes(market_packet('[Market_16_16]\nTotalStock=2\nCodeList=1A0001\nCodeList_1=1A0001\n'), 'USHI', instance=1, limit=10000)


def test_bj_selection_matches_d2_not_whole_three_board_market():
    body = market_packet('[Market_144_144]\nTotalStock=3\nCodeList=899001,899601\nCodeList_1=899050\n')
    assert market_codes(body, 'USTI', instance=1, limit=10000) == ['899050']


def test_utf8_name_and_exact_requested_set():
    fields = struct.pack('<IBBHIBBH', 5, 1, 0, 16, 55, 1, 0, 32)
    row = b'USHI1A0001'.ljust(16, b'\0') + '上证指数'.encode('utf8').ljust(32, b'\0')
    table = b'hx1.0\0' + struct.pack('<iIHHI', 1, 38, 48, 2, 0) + fields + row
    payload = struct.pack('<I', len(table)) + table
    body = struct.pack('<HiIHiB', 17, 2, 200, 1, len(payload), 1) + payload
    assert names(body, 'USHI', ['1A0001'], instance=2, limit=10000) == CATALOG[:1]
    with pytest.raises(ValueError):
        names(body, 'USHI', ['1B0300'], instance=2, limit=10000)


def test_daily_keeps_null_and_signed_values_and_checks_native_identity():
    fields = [1, 7, 8, 9, 11, 13, 19]
    table = dict(extra={5: 'USHI1A0001'}, fields=[(f, 4, 0, 4) for f in fields],
        rows=[dict(zip(fields, [20261113, None, 10, -1, 0, None, -3], strict=True))])
    rows = daily([table], '1A0001', 'USHI', date(2026, 11, 1), date(2026, 11, 13))
    assert rows == [['2026-11-13', None, '10', '-1', '0', None, '-3']]
    with pytest.raises(ValueError):
        daily([table], '1A0001', 'USZI', date(2026, 11, 1), date(2026, 11, 13))


def test_web_empty_and_failure_are_distinct_and_market_mapping_is_conservative():
    assert parse_members(member_html('899050', False), '899050') == dict(available=False, members=[])
    for body in ('', member_html().replace('</tbody>', ''), member_html().replace('code/1A0001', 'code/899050')):
        with pytest.raises(ValueError):
            parse_members(body, '1A0001')
    assert member_dataset.member_identity('600000') == '600000.SH'
    assert member_dataset.member_identity('510300') is None
    assert member_dataset.member_identity('00700') is None


def test_messages_are_separate_and_fingerprint_excludes_page_and_batch():
    e = envelope()
    d = member_dataset.normalize(e)
    changed = e.model_copy(update={'batch_id': 'other', 'raw_payload': {**e.raw_payload, 'page': 2}})
    assert member_dataset.fingerprint_plan(e, d) == member_dataset.fingerprint_plan(changed, member_dataset.normalize(changed))
    assert catalog_dataset.normalize(envelope(CATALOG_DATASET, payload=dict(catalog=CATALOG)))['row_count'] == 2
    assert unit_path('1A0001') == '$.units."1A0001"'
    with pytest.raises(ValueError):
        unit_path('1A0001";evil')
    p = envelope(PRICE_DATASET, payload=dict(code='1A0001', native_market='USHI', start='2026-11-01', through='2026-11-13',
        rows=ROWS, full=False, history_start=None))
    assert len(price_dataset.fingerprint_plan(p, price_dataset.normalize(p))[1]) == 13


def configured(cls=MemberCollector):
    c = cls()
    c.ingest = Publisher()
    c.session = SimpleNamespace(headers=lambda _: {})
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    c.query = SimpleNamespace(catalog=AsyncMock(return_value=CATALOG))
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw:
        httpx.Response(200, content=member_html('899050', False).encode('gb18030') if '899050' in url else member_html().encode('gb18030'))))
    return c


async def test_member_enqueues_all_before_archive_wait_and_explicit_empty_is_success():
    c = configured()
    async def confirm(*args):
        assert len(c.ingest.events) == 2
        assert c.ingest.events[-1].raw_payload['available'] is False
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result['unavailable'] == 1 and result['phase'] == 'complete'
    assert c.http.request.await_count == 2 and not c.records.add_error.called


async def test_member_failure_does_not_publish_empty_or_advance_failed_unit():
    c = configured()
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=b'bad' if '899050' in url else member_html().encode('gb18030'))
    with pytest.raises(ValueError):
        await c.execute()
    assert len(c.ingest.events) == 1 and c.ingest.state['cursor']['next_index'] == 1
    assert not c.confirmation.page_status.called
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=member_html('899050', False).encode('gb18030'))
    await c.execute()
    assert len(c.ingest.events) == 2


async def test_price_publishes_years_without_waiting_and_resumes_after_committed_year(monkeypatch):
    c = configured(PriceCollector)
    c.query.scope = AsyncMock(return_value=('2026-11-13', ['2026-11-12', '2026-11-13']))
    c.query.catalog.return_value = CATALOG[:1]
    c.query.plans = AsyncMock(return_value={'1A0001': dict(start='1900-01-01', through='2026-11-13', full=True, history_start=None)})
    c.fetch = AsyncMock(return_value=([['2025-12-31', *ROWS[0][1:]], *ROWS], datetime.now(UTC)))
    c.confirmation.page_status.side_effect = lambda *args: {'status': 'complete'} if len(c.ingest.events) == 2 else None
    result = await c.execute(fresh=True)
    assert result['phase'] == 'complete' and len(c.ingest.events) == 2
    assert c.ingest.events[0].raw_payload['start'] == '2025-01-01'
    assert all(e.raw_payload['history_start'] == '2025-12-31' for e in c.ingest.events)


def test_maximum_checkpoint_is_bounded():
    cursor = dict(work=[[f'{i:06}', 'USZI'] for i in range(1000)], trades=['2026-11-13']*10,
        current_plan=dict(start='1900-01-01', through='2026-11-13', full=True, history_start='1990-12-19'))
    assert len(json.dumps(cursor).encode()) < 32768


@pytest.mark.parametrize('value', ['bad', '1e10000', 'NaN', '0.00000000001', True])
def test_numeric_protocol_errors_are_validation_failures(value):
    with pytest.raises(ValueError):
        number(value)


async def test_native_identity_uses_shared_session_and_confirms_success(monkeypatch):
    from empire.plugins.infra.routing import USE_PROXY
    c = configured(PriceCollector)
    c.identity = SimpleNamespace(login=AsyncMock(return_value='session'), sessions=SimpleNamespace(confirm=Mock()))
    monkeypatch.setattr('empire.features.yuanhang_indices.collector_support.select_node', AsyncMock(return_value='node001'))
    operation = AsyncMock(return_value=['native result'])
    token = USE_PROXY.set(True)
    try:
        assert await c.authenticated(operation) == ['native result']
        c.identity.sessions.confirm.assert_called_once_with('node001','session')
    finally:
        USE_PROXY.reset(token)
