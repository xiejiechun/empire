"""Bounded source feasibility research. No collector, ingest or archive worker."""
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


@event.listens_for(Engine, 'before_cursor_execute')
def readonly(conn, cursor, statement, params, context, many):
    if statement.lstrip().split()[0].upper() not in {'SELECT', 'SHOW', 'START', 'ROLLBACK'}:
        raise RuntimeError('Research refuses SQL mutation')


def preview_text(raw):
    try:
        text = raw.decode('utf8')
    except UnicodeError:
        text = raw.decode('gb18030', errors='replace')
    return text


async def main():
    plan = json.loads((OUT / 'requests.json').read_text('utf8'))
    assert len(plan) <= 10
    cfg = load_config(ROOT / 'config.toml')
    cfg['http']['download_directory'] = str(OUT / 'temporary-downloads')
    manager = build_manager(cfg)
    counters = {}
    tokens = [USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counters)]
    results = dict(started_at=datetime.now(UTC).isoformat(), policy=dict(use_proxy=True, proxy_fallback=True),
                   requests=[], no_collectors=True, no_ingest=True, no_archive=True)
    try:
        await manager.start('infra.http')
        http = manager.registry.get('http.fetch')
        store = manager.registry.get('redis.store')
        results['pending_before'] = await store.client.xlen(store.stream)
        for item in plan:
            began = datetime.now(UTC).isoformat()
            result = dict(id=item['id'], method=item['method'], url=item['url'],
                          params=item.get('data') or item.get('json'), requested_at=began,
                          route_before=dict(counters))
            kwargs = {}
            if 'data' in item:
                kwargs['data'] = item['data']
            if 'json' in item:
                kwargs['content'] = json.dumps(item['json'], separators=(',', ':')).encode()
                kwargs['headers'] = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Referer': 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_xgzx_zf.html'}
            response = None
            try:
                policy = http.response_policy('generic')
                if item['mode'] == 'pdf':
                    policy = replace(http.file_policy(filename=item['id']+'.pdf', signature=b'%PDF-'),
                                     max_body_bytes=8*1024*1024, max_wire_bytes=8*1024*1024)
                response = await http.request(item['method'], item['url'],
                    allowed_domains=tuple(item['domains']), max_retries=1, total_timeout=40,
                    project_id='o7-feasibility', policy=policy, **kwargs)
                if item['mode'] == 'pdf':
                    result.update(status=response.status_code, artifact=response.artifact,
                                  acquired_at=datetime.now(UTC).isoformat())
                    continue
                raw = response.content
                result.update(status=response.status_code, bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(), acquired_at=datetime.now(UTC).isoformat())
                if item['mode'] == 'json':
                    body = response.json()
                    if 'ResultSets' in body:
                        result['source_error_code'] = body.get('ErrorCode')
                        result['sets'] = [dict(columns=s.get('ColName'), count=s.get('Count'),
                                               selected_rows=s.get('Content', [])[:2]) for s in body['ResultSets']]
                    elif isinstance(body, list):
                        result['results'] = body[:10]
                    else:
                        result['keys'] = sorted(body)
                        result['totalAnnouncement'] = body.get('totalAnnouncement')
                        result['hasMore'] = body.get('hasMore')
                        result['announcements'] = [{k:r.get(k) for k in ('secCode','secName','orgId',
                            'announcementId','announcementTitle','announcementTime','adjunctUrl','adjunctType')}
                            for r in (body.get('announcements') or [])[:40]]
                        if not result['announcements']:
                            result['small_response'] = body if len(raw) < 2000 else {'response_not_small': True}
                else:
                    body = preview_text(raw)
                    result['title'] = re.findall(r'<title[^>]*>(.*?)</title>', body, re.S)[:1]
                    result['scripts'] = re.findall(r'<script[^>]*src=[\"\x27]([^\"\x27]+)', body)[:20]
                    result['links'] = re.findall(r'(?:href|src)=[\"\x27]([^\"\x27]+)', body)[:40]
                    words = ['T005','T039','T040','T015','T022','T023','发行','上市','公告','实施','A股','股本','股份']
                    result['snippets'] = {word:[body[max(0,m.start()-120):m.end()+230]
                        for m in list(re.finditer(re.escape(word), body))[:8]] for word in words if word in body}
            except Exception as exc:
                result['error'] = redact(exc, cfg)
            finally:
                if response is not None:
                    response.close()
                if item['mode'] == 'pdf':
                    result['route_after'] = dict(counters)
                    results['requests'].append(result)
                    print(item['id'], result.get('status'), result.get('error', ''), flush=True)
            result['route_after'] = dict(counters)
            results['requests'].append(result)
            print(item['id'], result.get('status'), result.get('error', ''), flush=True)
        results['pending_after'] = await store.client.xlen(store.stream)
        results['network'] = counters
    finally:
        await manager.shutdown()
        USE_PROXY.reset(tokens[0]); PROXY_FALLBACK.reset(tokens[1]); ROUTE_COUNTS.reset(tokens[2])
    results['finished_at'] = datetime.now(UTC).isoformat()
    with (OUT / sys.argv[1]).open('x', encoding='utf8', newline='\n') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


asyncio.run(main())
