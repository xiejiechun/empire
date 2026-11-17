"""ETF source identities, complete sets and shared transport ownership."""
import copy
import json
import struct
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.etree.ElementTree import Element

import pytest

from empire.contracts.native_stream import StreamTarget
from empire.features.yuanhang_etf import contract, native
from empire.sources import yuanhang_transport
from empire.sources.yuanhang_auth import ClientDevice, GuestSession, _passport

CATALOG = [dict(code='159653.SZ', name='ESG300ETF国联安', native_market='USZJ'),
           dict(code='511980.SH', name='货币ETF汇添富', native_market='USHJ')]
ROWS = [['2026-11-13', '100.058', '100.058', '100.045', '100.045', None, '60029']]


def latest_rows():
    return [dict(r, quote_at=None, net_value_date=None, **dict.fromkeys(contract.LATEST_FIELDS.values(),
        '100' if r['code'] == '511980.SH' else '1.5')) for r in CATALOG]


def configured():
    from empire.features.yuanhang_etf.price_collector import PriceCollector
    from tests.prefetch_source import prefetch_http
    from tests.test_capital_lifecycle import Publisher
    c = PriceCollector()
    c.ingest, c.http = Publisher(), prefetch_http()
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    async def plans(codes, through, trades, **kwargs):
        return {code: dict(start='2026-01-01', through=through, full=kwargs.get('scope') == 'backfill', history_start=None) for code in codes}
    c.query = SimpleNamespace(catalog=AsyncMock(return_value=CATALOG), scope=AsyncMock(return_value=(
        '2026-11-13', ['2026-11-13'])), plans=AsyncMock(side_effect=plans))
    c.fetch = AsyncMock(return_value=(ROWS, datetime.now(UTC)))
    return c


def packet(rows, fields=(5, 55), *, total=None, request_id=7):
    widths = {5: 16, 55: 192}
    descriptors = b''.join(struct.pack('<IBBH', f, 1 if f in widths else 4, 0, widths.get(f, 4)) for f in fields)
    body = b''
    for row in rows:
        for field in fields:
            value = row[field]
            if field in widths:
                body += value.encode('utf8').ljust(widths[field], b'\0')
            else:
                body += struct.pack('<i', -2147483648 if value is None else value)
    extra = struct.pack('<IBBHi', 34056, 4, 0, 4, len(rows) if total is None else total) if request_id == 7 else b''
    table = b'hx1.0\0' + struct.pack('<iIHHI', len(rows), 22+len(descriptors), sum(widths.get(f, 4) for f in fields), len(fields), len(extra))
    table += descriptors + body + extra
    payload = struct.pack('<I', len(table)) + table
    return struct.pack('<HiIHiB', 17, 1, request_id, 1, len(payload), 1) + payload


def test_etf_catalog_uses_source_total_utf8_names_and_exact_identity():
    rows = [{5: 'USZJ159653', 55: 'ESG300ETF国联安'}, {5: 'USHJ511980', 55: '货币ETF汇添富'}]
    reserved = []
    actual = native.catalog(packet(rows), 10000, reserved.append)
    assert [r['code'] for r in actual] == ['159653.SZ', '511980.SH']
    assert actual[1]['name'] == '货币ETF汇添富' and reserved
    for bad in [packet(rows, total=3), packet([rows[0], rows[0]]), packet(rows)[:-1], packet(rows, request_id=200)]:
        with pytest.raises(ValueError):
            native.catalog(bad, 10000)
    with pytest.raises(ValueError):
        native.catalog(packet([{5: 'USHA511980', 55: 'wrong asset'}]), 10000)


def test_etf_latest_equal_count_different_set_rejected_and_unknown_dates_remain_unknown():
    fields = (5, 55, 56, *contract.LATEST_FIELDS)
    row = {5: 'USHJ511980', 55: '货币ETF汇添富', 56: None, **dict.fromkeys(contract.LATEST_FIELDS, 100)}
    body = packet([row], fields, request_id=200)
    actual = native.latest(body, 'USHJ', ['511980.SH'], 10000)[0]
    assert actual['quote_at'] is actual['net_value_date'] is None
    assert actual['latest'] == actual['net_value'] == '100'
    with pytest.raises(ValueError):
        native.latest(body, 'USHJ', ['510010.SH'], 10000)
    with pytest.raises(ValueError):
        native.latest(body, 'USZJ', ['511980.SH'], 10000)
    with pytest.raises(ValueError):
        native.latest(packet([row, row], fields, request_id=200), 'USHJ', ['511980.SH'], 10000)


def test_etf_daily_keeps_precision_null_and_validates_market_and_dates():
    fields = [1, 7, 8, 9, 11, 13, 19]
    table = dict(extra={5: 'USHJ511980'}, fields=[(f, 4, 0, 4) for f in fields],
        rows=[dict(zip(fields, [20261113, '100.058', '100.058', '100.045', '100.045', None, '60029'], strict=True))])
    assert native.daily([table], '511980.SH', 'USHJ', date(2026, 11, 1), date(2026, 11, 13)) == [
        ['2026-11-13', '100.058', '100.058', '100.045', '100.045', None, '60029']]
    with pytest.raises(ValueError):
        native.daily([table], '511980.SH', 'USZJ', date(2026, 11, 1), date(2026, 11, 13))
    with pytest.raises(ValueError):
        contract.number('0.00000000001')
    with pytest.raises(ValueError):
        contract.identity('511980', 'USHJ')


def test_authenticated_service_directory_preserves_tags_and_rejects_missing_service():
    item = Element('item', passport='UserID=fixture|M_hqdns=hq.10jqka.com.cn:9602:16;32;,block.10jqka.com.cn:9602:block;search;|signlength=4', signature='ABCD')
    session = _passport(item, 'fixture', ClientDevice('02-00-00-00-00-01'), 'node001')
    assert session.targets_for('block')[0].host == 'block.10jqka.com.cn'
    assert session.targets_for('16')[0] == session.servers[0]
    with pytest.raises(ValueError, match='unavailable'):
        session.targets_for('missing')
    assert 'fixture' not in repr(session)


async def test_shared_service_transport_decodes_closes_and_keeps_node_binding():
    target = StreamTarget('block.10jqka.com.cn', 9602, 'https://10jqka.com.cn/', ('10jqka.com.cn',))
    session = GuestSession('fixture', 'secret', 'device', (target,), 'node001', (('block', (target,)),))
    class Http:
        def response_policy(self, _):
            return SimpleNamespace(max_body_bytes=1000)

        async def request_stream(self, actual, exchange, **kwargs):
            assert actual == target and kwargs['proxy_code'] == 'node001'
            assert kwargs['connection_key'] is session and kwargs['max_retries'] == 0
            self.response = SimpleNamespace(content=b'body', reserve_decoded=lambda n: None, close=lambda: setattr(self, 'closed', True))
            return self.response
    http = Http()
    with pytest.raises(ValueError, match='decode'):
        await yuanhang_transport.request(http, session, b'id=7', lambda *args: (_ for _ in ()).throw(ValueError('decode')),
            project_id=contract.CATALOG_PROJECT, service='block')
    assert http.closed


async def test_etf_collects_all_units_before_waiting_for_archive():
    c = configured()
    async def confirm(*args):
        assert len(c.ingest.events) == 2
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    await c.execute(fresh=True)
    assert c.fetch.await_count == 2
    assert c.ingest.state['cursor']['phase'] == 'complete'


async def test_etf_failure_keeps_preceding_published_cursor_and_resume():
    c = configured()
    c.fetch.side_effect = [(ROWS, datetime.now(UTC)), ValueError('fixture failure')]
    with pytest.raises(ValueError, match='fixture failure'):
        await c.execute(fresh=True)
    assert len(c.ingest.events) == 1 and c.ingest.state['cursor']['next_index'] == 1
    c.fetch.side_effect = None
    c.fetch.return_value = (ROWS, datetime.now(UTC))
    await c._round('backfill')
    assert len(c.ingest.events) == 2 and c.ingest.events[-1].raw_payload['code'] == '511980.SH'


async def test_etf_5000_pool_cursor_bounded_and_backfill_limited_to_64():
    c = configured()
    pool = [dict(code=f'{n:06d}.SH', native_market='USHJ', name='测试ETF') for n in range(5000)]
    c.query.catalog.return_value = pool
    observed = []
    advance = c.ingest.advance_checkpoint
    async def bound(**kwargs):
        observed.append(len(json.dumps(kwargs['cursor'], ensure_ascii=False).encode()))
        return await advance(**kwargs)
    c.ingest.advance_checkpoint = bound
    await c._round('backfill')
    assert c.fetch.await_count == 64 and max(observed) < 16384
    c.fetch.reset_mock()
    await c._round('recent')
    assert c.fetch.await_count == 5000 and max(observed) < 16384


async def test_etf_changed_pool_never_resumes_old_scope_and_fresh_replans():
    c = configured()
    c.fetch.side_effect = ValueError('stop')
    with pytest.raises(ValueError):
        await c._round('backfill')
    c.query.catalog.return_value = CATALOG[:1]
    with pytest.raises(ValueError, match='目录或选择范围'):
        await c._round('backfill')
    c.fetch.side_effect = None
    c.fetch.return_value = (ROWS, datetime.now(UTC))
    await c._round('backfill', force=True)
    assert len(c.ingest.events) == 1


async def test_live_schedule_trade_calendar_manual_and_no_partial_publish():
    from empire.contracts.collector import COLLECTION_ORIGIN
    from empire.core.time import CHINA
    from empire.features.yuanhang_etf.live import LiveCollector
    from tests.prefetch_source import prefetch_http
    c = LiveCollector()
    c.calendar = SimpleNamespace(month=AsyncMock(return_value=dict(complete=True,
        rows=[dict(trade_date='2026-11-16', is_trade=True)])))
    token = COLLECTION_ORIGIN.set('schedule')
    try:
        assert await c.should_sample(datetime(2026, 11, 16, 10, tzinfo=CHINA))
        assert not await c.should_sample(datetime(2026, 11, 16, 12, tzinfo=CHINA))
        assert not await c.should_sample(datetime(2026, 11, 16, 18, tzinfo=CHINA))
        c.calendar.month.return_value['complete'] = False
        with pytest.raises(ValueError, match='完整'):
            await c.should_sample(datetime(2026, 11, 16, 10, tzinfo=CHINA))
    finally:
        COLLECTION_ORIGIN.reset(token)
    assert await c.should_sample(datetime(2026, 11, 16, 18, tzinfo=CHINA))
    c.directory, c.http = SimpleNamespace(catalog=AsyncMock(return_value=CATALOG)), prefetch_http()
    c.ingest, c.store = SimpleNamespace(publish_volatile=AsyncMock()), SimpleNamespace(save=AsyncMock())
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.fetch = AsyncMock(return_value=latest_rows()[:1])
    with pytest.raises(ValueError, match='目录集合'):
        await c.execute()
    c.ingest.publish_volatile.assert_not_called()


def test_latest_payload_identity_proof_nulls_and_time_contract():
    from empire.features.yuanhang_etf.latest import validate
    snapshot = dict(schema=1, catalog_hash=contract.digest(CATALOG), observed_at=datetime.now(UTC).isoformat(), rows=latest_rows())
    validate(snapshot)
    wrong = copy.deepcopy(snapshot)
    wrong['rows'][0]['name'] = 'same count different identity content'
    with pytest.raises(ValueError, match='集合证明'):
        validate(wrong)
    wrong = copy.deepcopy(snapshot)
    wrong['rows'][0]['quote_at'] = snapshot['observed_at']
    with pytest.raises(ValueError, match='来源报价'):
        validate(wrong)


async def test_empty_history_requires_exact_current_identity_and_no_quote_values():
    from empire.features.yuanhang_etf.price_collector import PriceCollector
    from empire.sources.yuanhang_wire import EmptyHistoryResponse
    c = configured()
    c.catalog_names = {r['code']: r['name'] for r in CATALOG}
    c.plans = {'511980.SH': dict(start='1900-01-01', through='2026-11-13')}
    quote = dict(CATALOG[1], **dict.fromkeys(contract.LATEST_FIELDS.values()))
    c.authenticated = AsyncMock(side_effect=[EmptyHistoryResponse(1, 210), [quote]])
    assert (await PriceCollector.fetch(c, ['511980.SH', 'USHJ'], reservation=None))[0] is None
    c.authenticated = AsyncMock(side_effect=[EmptyHistoryResponse(1, 210), [dict(quote, latest='100')]])
    with pytest.raises(ValueError, match='矛盾'):
        await PriceCollector.fetch(c, ['511980.SH', 'USHJ'], reservation=None)


async def test_source_gap_is_not_an_empty_history_proof_and_valid_siblings_clear():
    from empire.contracts.collector import CollectionSourceGap
    c = configured()
    async def fetch(item, *, reservation):
        return (None if item[0] == '511980.SH' else ROWS), datetime.now(UTC)
    c.fetch = AsyncMock(side_effect=fetch)
    with pytest.raises(CollectionSourceGap, match='未写空历史或覆盖证明'):
        await c.execute()
    assert c.stats['status'] == 'source_gap'
    assert all(e.raw_payload['code'] == '159653.SZ' and e.raw_payload['rows'] for e in c.ingest.events)
    assert sum(call.args[0][0] == '511980.SH' for call in c.fetch.call_args_list) == 1
    assert c.confirmation.page_status.called


@pytest.mark.parametrize('value', ['-0', '01', '1.0', '1e3', 'NaN', 'null', '', '0.00000000001', '1000000000000000000', True])
def test_latest_rejects_noncanonical_or_out_of_range_numeric(value):
    from empire.features.yuanhang_etf.latest import validate
    rows = latest_rows()
    rows[0]['latest'] = value
    with pytest.raises(ValueError, match='数值'):
        validate(dict(schema=1, catalog_hash=contract.digest(CATALOG), observed_at=datetime.now(UTC).isoformat(), rows=rows))


def test_latest_compression_is_one_format_and_bounded_before_json(monkeypatch):
    import base64
    import zlib

    from empire.features.yuanhang_etf import latest
    valid = 'z1:'+base64.b64encode(zlib.compress(b'{"schema":1}')).decode()
    assert latest.decode_body(valid) == {'schema': 1}
    for body in ['{}', 'z1:?', valid[:-4], valid+base64.b64encode(b'extra').decode()]:
        with pytest.raises(ValueError):
            latest.decode_body(body)
    monkeypatch.setattr(latest, 'LATEST_BYTES', 100)
    large = 'z1:'+base64.b64encode(zlib.compress(b'x'*1000)).decode()
    with pytest.raises(ValueError, match='解压超限'):
        latest.decode_body(large)
