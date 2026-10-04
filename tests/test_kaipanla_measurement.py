"""Evidence failures and deletion confinement for the standalone storage experiment."""
import importlib.util
import json
import zlib
from datetime import date
from pathlib import Path
from urllib.parse import quote_from_bytes

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measure_support', ROOT / 'scripts/kaipanla_measure_support.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def packed(value):
    return json.dumps(value).encode()


def test_same_count_different_minute_set_is_not_complete():
    rows = [[t, 10, 10, 1, 0] for t in support.TREND_TIMES]
    rows[1] = rows[0][:]
    with pytest.raises(ValueError, match='minute_key_gap_or_duplicate'):
        support.validate(packed(dict(errcode=0, code='000001', day=20260930, trend=rows)),
                         'GetStockTrend', '000001', date(2026, 9, 30))


def test_same_second_source_points_remain_and_truncated_total_fails():
    rows = [['09:30:00', 10, 1, 2, 0, 0, 0, 1], ['09:30:00', 11, 2, 3, 0, 0, 0, 2]]
    value = dict(errcode=0, Day=20260930, fb=rows, Count=2, total=2)
    info = support.validate(packed(value), 'GetStockFenBi2', '000001', date(2026, 9, 30))
    assert info['rows'] == 2 and info['distinct_time_labels'] == 1
    value['total'] = 3
    with pytest.raises(ValueError, match='partial_or_inconsistent_source_count'):
        support.validate(packed(value), 'GetStockFenBi2', '000001', date(2026, 9, 30))


def test_exact_bytes_compression_measurement_and_only_owned_cleanup(tmp_path):
    import gzip
    sibling = tmp_path / 'user-data'
    sibling.mkdir()
    (sibling / 'keep').write_bytes(b'keep')
    capture = support.Capture(tmp_path)
    writer = capture.open('000001.SZ')
    body = b'{"array":[1,1],"spacing": "exact"}'
    writer.write('GetStockTrend', body)
    writer.close()
    raw = (capture.raw / '000001.SZ.pack').read_bytes()
    assert raw.endswith(body)
    assert gzip.decompress((capture.compressed / '000001.SZ.pack.gz').read_bytes()) == raw
    measure = capture.measure()
    assert measure['raw']['logical_bytes'] == len(raw)
    assert measure['raw']['allocated_bytes'] >= len(raw)
    assert capture.cleanup()['deleted']
    assert (sibling / 'keep').read_bytes() == b'keep'


def test_changed_ownership_refuses_deletion(tmp_path):
    capture = support.Capture(tmp_path)
    (capture.root / '.owner').write_text('someone-else')
    with pytest.raises(RuntimeError, match='ownership_changed'):
        capture.cleanup()
    assert capture.root.exists()


def test_source_codec_is_lossless_and_bounded():
    body = b'{"price":[1,1],"book":[[2,3]]}'
    encoded = quote_from_bytes(zlib.compress(body), safe='').replace('%20', '+').encode()
    assert support.decode_body(encoded) == body
    with pytest.raises(ValueError, match='decoded_limit'):
        support.decode_body(encoded, maximum=4)
    with pytest.raises(ValueError, match='incomplete_or_trailing'):
        support.decode_body(quote_from_bytes(zlib.compress(body)[:-2], safe='').encode())


def test_replay_price_book_alignment_and_unindexed_points():
    keys = [int(t.replace(':', '')) for t in support.TREND_TIMES]
    keys.insert(keys.index(1301), 1300)
    value = dict(trendList=[['92500', 1, 2, 3, 4, 5], ['150000', 1, 2, 3, 4, 5]],
                 trendListFengDan=[['92500'] + [0] * 12, ['150000'] + [0] * 12],
                 trendListIndex=[keys, ['0,0'] * 241 + ['1,1']])
    assert support.replay_evidence(value)['orderbook_rows'] == 2
    value['trendList'][-1][0] = '150058'
    value['trendListFengDan'][-1][0] = '150058'
    assert support.replay_evidence(value)['last_time'] == '150058'
    value['trendListIndex'][1][-1] = '0,0'
    with pytest.raises(ValueError, match='incomplete_day_or_unindexed'):
        support.replay_evidence(value)
    value['trendListFengDan'][1][0] = '145959'
    with pytest.raises(ValueError, match='time_alignment'):
        support.replay_evidence(value)


def test_standalone_routes_every_request_through_proxy_and_cleans_partial_results(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('measure_cli', ROOT / 'scripts/measure_kaipanla_day.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr(cli, 'load_config', lambda _: {'http': {}})
    started = []
    calls = []
    directory = None

    class Budget:
        async def reserve(self, size):
            assert size <= 512 * 1024 * 1024
            return SimpleNamespace(release=lambda: None)

    class Http:
        global_limit = 2
        buffer_budget = Budget()

        def file_policy(self, **kwargs):
            return SimpleNamespace(filename=kwargs['filename'])

        async def settings(self):
            return [{'name': 'kaipanla'}]

        async def request(self, method, url, **kwargs):
            assert USE_PROXY.get() is True and PROXY_FALLBACK.get() is False
            assert kwargs['project_id'] == 'kaipanla-storage-measure'
            options = kwargs['attempt_options']()['data']
            assert 'Token' not in options and 'UserID' not in options
            action, code = options['a'], options['StockID']
            calls.append((code, action))
            ROUTE_COUNTS.get()['proxy_requests'] = len(calls)
            field, width = support.INTERFACES[action]
            value = dict(errcode=0, code=code, day=20260930)
            if code == '000002' and action == 'GetStockBid':
                value['errcode'] = 1017
            elif action == 'StockTrendInfo':
                assert (options['c'], options['start'], options['stop'], options['isAll']) == (
                    'HisSuperFuPan', '0', '0', '1')
                keys = [int(t.replace(':', '')) for t in support.TREND_TIMES]
                keys.insert(keys.index(1301), 1300)
                value.update(trendList=[['92500', 1, 2, 3, 4, 5], ['150058', 1, 2, 3, 4, 5]],
                    trendListFengDan=[['92500'] + [0] * 12, ['150058'] + [0] * 12],
                    trendListIndex=[keys, ['0,0'] * 241 + ['1,1']], MinDate='2026-04-04')
            elif action == 'GetStockPanKou':
                value.update(real={'last_px': 10}, weituo={'b1': [10, 100]})
            elif action == 'GetStockChouMa_New':
                value.update(List=[[0] * 11], Total=1, State=1)
            else:
                times = (['09:15', '09:24'] if action == 'GetStockBid' else
                         ['09:30:00', '09:30:00'] if action == 'GetStockFenBi2' else support.TREND_TIMES)
                value[field] = [[t] + [10] * (width - 1) for t in times]
                if action == 'GetStockFenBi2':
                    value.update(Count=2, total=2)
            body = packed(value)
            if action == 'StockTrendInfo':
                body = quote_from_bytes(zlib.compress(body), safe='').replace('%20', '+').encode()
            path = directory / kwargs['policy'].filename
            path.write_bytes(body)
            return SimpleNamespace(status_code=200, artifact={'path': str(path)}, close=lambda: None)

    async def plan():
        return ([{'code': code, 'market': 'SZ', 'unified_code': code + '.SZ'}
                 for code in ('000001', '000002')], [date(2026, 9, 30)])

    async def refresh(**kwargs):
        pass

    def factory(cfg):
        nonlocal directory
        directory = Path(cfg['http']['download_directory'])
        values = {'http.fetch': Http(), 'kaipanla_trend.query': SimpleNamespace(plan=plan),
                  'proxy.pool': SimpleNamespace(refresh=refresh, healthy_count=lambda: 2)}
        class Manager:
            registry = SimpleNamespace(get=lambda key: values[key])
            async def start(self, name):
                started.append(name)
            async def shutdown(self):
                started.append('shutdown')
        return Manager()

    monkeypatch.setattr(cli, 'build_manager', factory)
    args = SimpleNamespace(config=None, day=None, symbols=None, limit=0, workers=2,
                           request_timeout=120, report=str(tmp_path / 'result.json'))
    report = asyncio.run(cli.measure(args))
    assert started == ['infra.http', 'data.kaipanla_trend', 'shutdown']
    assert len(calls) == 2 * len(support.INTERFACES)
    assert report['valid_known_stocks'] == 1 and not report['known_scope_complete']
    assert report['cleanup']['deleted'] and not directory.parent.exists()
    assert report['by_interface']['StockTrendInfo']['valid_stocks'] == 2
    assert report['storage']['raw']['logical_bytes'] > report['storage']['gzip']['logical_bytes']
