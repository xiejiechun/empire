"""Anonymous historical source protocol; never reads account/session configuration."""
import hashlib
import json
import re
from functools import partial

from empire.features.kaipanla.alias_source import resolve
from empire.features.kaipanla.pair_parser import combine_day, parse_response
from empire.features.kaipanla.source_protocol import DOMAIN, URL, SourceError, request_options
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


async def fetch_part(collector, code, day, kind, market=None, listed=None):
    """Use Empire's shared routing, retries, rate limits and byte reservations."""
    await wait_for_capacity(collector.ingest, collector.stats)
    request_options(code, day, kind)  # Validate before requesting resource admission.
    response = await collector.http.request('POST', URL,
        attempt_options=partial(request_options, code, day, kind), max_redirects=0,
        allowed_domains=(DOMAIN,), project_id=collector.project_id,
        policy=collector.http.response_policy('generic'), max_retries=collector.request_retries)
    return await consume_part(collector, response, code, day, kind, market, listed)


async def consume_part(collector, response, code, day, kind, market=None, listed=None):
    """The ordered consumer alone validates a downloaded response and alias identity."""
    body = response.content
    diagnostic = dict(request_url=URL, status_code=response.status_code,
                      raw_body=body[:65536], observed_bytes=len(body),
                      body_sha256=hashlib.sha256(body).hexdigest(),
                      metadata=dict(code=code, day=day.isoformat(), kind=kind))
    try:
        payload = json.loads(body)
        source_code = payload.get('code') if isinstance(payload, dict) else None
        aliases = {}
        if (source_code != code and market == 'BJ' and listed
                and isinstance(source_code, str) and re.fullmatch(r'[48][0-9]{5}', source_code)):
            # Validate and consume this body before taking another HTTP reservation.
            # Otherwise the minimum legal single-response budget would deadlock
            # while awaiting an alias lookup with the first response still held.
            parsed = parse_response({**payload, 'code': code}, code, day, kind)
            response.close()
            del body, payload
            proof = await resolve(collector, code, source_code, listed)
            return {**parsed, 'source_code': source_code, 'alias': proof}
        return parse_response(payload, code, day, kind, aliases)
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, SourceError):
            diagnostic['metadata'].update(category=exc.category, **exc.details)
        if not getattr(exc, 'diagnostic_recorded', False):
            exc.diagnostic_recorded = await record_error_safely(
                collector.records, collector.stats, collector.project_id, exc,
                stage='source_validation', unavailable_message='开盘啦错误样本暂未写入 Redis', fields=diagnostic)
        raise
    finally:
        response.close()


async def fetch_day(collector, code, day, market=None, listed=None):
    trend = await fetch_part(collector, code, day, 'trend', market, listed)
    auction = await fetch_part(collector, code, day, 'auction', market, listed)
    return combine_day(trend, auction)
