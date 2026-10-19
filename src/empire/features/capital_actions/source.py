"""TDX-specific complete-response verification; transport remains the shared downloader."""
import hashlib
import json
from datetime import UTC, datetime

from empire.features.capital_actions.parser import parse
from empire.features.capital_actions.source_protocol import ENTRIES, PAGE_URL
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


async def complete_response(collector, kind, report_date=None, *, reservation=None, defer=False):
    started = datetime.now(UTC)
    capacity = 10000
    await wait_for_capacity(collector.ingest, collector.stats)
    params = (['0', '0', report_date, 'szzs desc', '', '0', '1', str(capacity)] if kind == 'dividends'
              else ['0', '', '1', '1', str(capacity)] if kind == 'additional_issues'
              else ['', '1', '1', str(capacity)])
    response = await collector.http.request('POST',
        'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.' + ENTRIES[kind],
        content=json.dumps({'Params': params}, separators=(',', ':')).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                 'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE_URL},
        allowed_domains=('tdx.com.cn',), project_id=collector.project_id,
        policy=collector.http.response_policy('generic'), max_retries=collector.request_retries,
        reservation=reservation)
    async def consume():
        try:
            rows, _ = parse(kind, response.json(), capacity, report_date)
        except (ValueError, TypeError, KeyError) as exc:
            content = response.content
            exc.diagnostic_recorded = await record_error_safely(
                collector.records, collector.stats, collector.project_id, exc,
                stage='source_validation', unavailable_message='错误样本暂未写入 Redis',
                fields=dict(request_url='http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.' + ENTRIES[kind],
                    status_code=response.status_code, raw_body=content[:65536],
                    observed_bytes=len(content), body_sha256=hashlib.sha256(content).hexdigest(),
                    metadata={'kind': kind, 'report_date': report_date, 'capacity': capacity}))
            raise
        finally:
            if not defer:
                response.close()
        return rows, started

    if defer:
        return DeferredResponse(response, consume)
    return await consume()
