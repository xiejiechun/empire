import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from empire.features.stocks.ths_collector import ThsUniverseCollector
from empire.features.stocks.ths_source import REQUEST, parse_directory
from empire.plugins.collection.records import RecordsPlugin
from tests.test_sina_universe import MemoryIngest


def document(codes=('920627', '300522', '688196')):
    rows = []
    for number, code in enumerate(codes, 1):
        anchor = f'<a href="http://stockpage.10jqka.com.cn/{code}/">'
        rows.append(f'<tr><td>{number}</td><td>{anchor}{code}</a></td>'
                    f'<td>{anchor}股票{code}</a></td>' + '<td>--</td>' * 11 + '</tr>')
    return '<table class="m-table"><tbody>' + ''.join(rows) + '</tbody></table>' + (
        f"<input id='request' value='{json.dumps(REQUEST)}'>"
        "<input id='baseUrl' value='index/index'><div class='m-pager'></div>")


class Source:
    def __init__(self, content):
        self.content, self.calls = content, []

    def response_policy(self, profile):
        assert profile == 'stocks'
        return None

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return httpx.Response(200, content=self.content.encode('gb18030'))


def collector(content):
    item = ThsUniverseCollector()
    item.http, item.ingest = Source(content), MemoryIngest()
    item.session = SimpleNamespace(headers=lambda referer: {'Referer': referer})
    item.records = RecordsPlugin()

    async def confirmed(*args):
        assert item.ingest.state['cursor']['phase'] == 'complete'
        return {'status': 'complete'}
    item.confirmation = SimpleNamespace(stock_status=confirmed)
    return item


def test_complete_set_has_markets_leading_zero_and_link_identity():
    rows = parse_directory(document(('920627', '000001', '688196')))
    assert {r['unified_code'] for r in rows} == {'920627.BJ', '000001.SZ', '688196.SH'}
    assert [r['source_symbol'] for r in rows] == sorted((r['source_symbol'] for r in rows), reverse=True)


@pytest.mark.parametrize('change', [
    lambda s: s.replace('300522', '920627'),
    lambda s: s.replace('<td>2</td>', '<td>3</td>'),
    lambda s: s.replace('/300522/', '/600519/', 1),
    lambda s: s.replace('</tbody></table>', ''),
    lambda s: s.replace("class='m-pager'></div>", "class='m-pager'>1/2</div>"),
    lambda s: s.replace('"size": "10000"', '"size": "20"'),
    lambda s: s.replace('<td>--</td>', '', 1),
    lambda s: '<html>验证或登录页面</html>',
    lambda s: document(()),
])
async def test_bad_complete_set_never_advances_checkpoint(change):
    item = collector(change(document()))
    with pytest.raises(ValueError):
        await item.execute()
    assert item.ingest.state['revision'] == 0 and not item.ingest.events


async def test_normal_round_requests_once_and_waits_only_after_all_chunks():
    item = collector(document(tuple(f'{600000 + n:06d}' for n in range(161))))
    result = await item.execute()
    assert result['collected'] == 161
    assert len(item.http.calls) == 1
    assert [e.raw_payload.get('page') for e in item.ingest.events] == [1, 2, 3, None]
    assert item.ingest.releases == 1


async def test_explicit_fresh_fetches_again_after_complete_checkpoint():
    item = collector(document())
    await item.execute()
    previous = item.ingest.state['cursor']['snapshot_id']
    await item.execute(fresh=True)
    assert len(item.http.calls) == 2
    assert item.ingest.state['cursor']['snapshot_id'] != previous


def test_pinned_directory_session_generates_current_token_without_network():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        'from PySide6.QtCore import QCoreApplication; '
        'from empire.plugins.collectors.ths_session import ThsDirectorySession; '
        'app=QCoreApplication([]); '
        'h=ThsDirectorySession().headers("https://q.10jqka.com.cn/"); '
        'assert len(h["Cookie"]) == 62; assert h["User-Agent"] == "Mozilla/5.0"; '
        'print("verified")'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'verified'


async def test_interrupted_queue_rechecks_same_set_and_resumes_without_duplicate_pages():
    item = collector(document(tuple(f'{600000 + n:06d}' for n in range(161))))
    publish = item.ingest.publish_page

    async def interrupt(envelopes, **kwargs):
        if envelopes[0].raw_payload.get('page') == 2:
            raise asyncio.CancelledError()
        return await publish(envelopes, **kwargs)
    item.ingest.publish_page = interrupt
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    assert item.ingest.state['cursor']['next_page'] == 2
    assert item.ingest.releases == 1
    item.ingest.publish_page = publish
    await item.execute()
    assert [e.raw_payload.get('page') for e in item.ingest.events] == [1, 2, 3, None]
    assert len(item.http.calls) == 2


async def test_changed_set_after_interrupt_starts_new_snapshot():
    item = collector(document())
    await item.execute()
    old = item.ingest.state['cursor']['snapshot_id']
    item.ingest.state['cursor']['phase'] = 'pages'
    item.http.content = document(('920627', '000001', '688196'))
    await item.execute()
    assert item.ingest.state['cursor']['snapshot_id'] != old
