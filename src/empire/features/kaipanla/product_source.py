"""Business arrays from one complete source response, with explicit identity proof."""
import hashlib
import json
import re
from functools import partial

from empire.features.kaipanla.alias_source import resolve
from empire.features.kaipanla.contract import PRODUCTS
from empire.features.kaipanla.parser import parse
from empire.features.kaipanla.source_protocol import DOMAIN, URL, request_options
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


def options(code, day, kind):
    result = request_options(code, day, 'trend')
    result['data']['a'] = PRODUCTS[kind].action
    return result


async def consume(collector, response, stock, day):
    body = response.content
    diagnostic = dict(request_url=URL, status_code=response.status_code, raw_body=body[:65536],
        observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
        metadata=dict(code=stock['code'], day=day.isoformat(), kind=collector.kind))
    try:
        payload = json.loads(body)
        source_code = payload.get('code') if isinstance(payload, dict) else None
        aliases = {}
        if (source_code and source_code != stock['code'] and stock['market'] == 'BJ'
                and re.fullmatch(r'[48][0-9]{5}', source_code)):
            # Validate and release the first body before reserving an alias
            # response, matching the shared source memory ownership contract.
            parsed = parse({**payload, 'code': stock['code']}, stock['code'], day, collector.kind)
            response.close()
            del body, payload
            proof = await resolve(collector, stock['code'], source_code, stock['listing_date'])
            return {**parsed, 'source_code': source_code, 'aliases': {source_code: proof}}
        return parse(payload, stock['code'], day, collector.kind, aliases)
    except (ValueError, TypeError, KeyError) as exc:
        if not getattr(exc, 'diagnostic_recorded', False):
            exc.diagnostic_recorded = await record_error_safely(collector.records, collector.stats,
                collector.project_id, exc, stage='source_validation',
                unavailable_message='开盘啦错误记录暂不可用', fields=diagnostic)
        raise
    finally:
        response.close()


async def fetch(collector, stock, day, lease, policy):
    await wait_for_capacity(collector.ingest, collector.stats)
    return await collector.http.request('POST', URL,
        attempt_options=partial(options, stock['code'], day, collector.kind), max_redirects=0,
        allowed_domains=(DOMAIN,), project_id=collector.project_id,
        policy=policy, reservation=lease, max_retries=collector.request_retries)
