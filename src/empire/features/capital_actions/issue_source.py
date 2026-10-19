"""Fetch each required issue detail through the shared bounded downloader."""
import hashlib
import json

from empire.features.capital_actions.contract import unit_key, validate_rows
from empire.features.capital_actions.issue_contract import parse, validate
from empire.features.capital_actions.source_protocol import PAGE_URL, URL
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


async def fetch_detail(c, row, aliases, *, reservation=None, defer=False):
    await wait_for_capacity(c.ingest, c.stats)
    source_id = row['data']['source_id']
    response = await c.http.request('POST', URL,
        content=json.dumps({'Params': [source_id]}, separators=(',', ':')).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                 'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE_URL},
        allowed_domains=('tdx.com.cn',), project_id=c.project_id,
        policy=c.http.response_policy('generic'), max_retries=c.request_retries, reservation=reservation)
    async def consume():
        try:
            return parse(response.json(), row, aliases)
        except (ValueError, TypeError, KeyError) as exc:
            content = response.content
            exc.diagnostic_recorded = await record_error_safely(c.records, c.stats, c.project_id, exc,
                stage='source_validation', unavailable_message='增发详情错误样本暂未写入 Redis',
                fields=dict(request_url=URL, status_code=response.status_code, raw_body=content[:65536],
                    observed_bytes=len(content), body_sha256=hashlib.sha256(content).hexdigest(),
                    metadata={'source_id': source_id, 'code': row['code']}))
            raise
        finally:
            if not defer:
                response.close()

    if defer:
        return DeferredResponse(response, consume)
    return await consume()


def reusable_details(candidates, source_rows):
    """Reuse only valid archived details whose list business content still matches."""
    current = {row['data']['source_id']: row['data'] for row in source_rows}
    reusable, conflicted = {}, set()
    for row in candidates:
        try:
            validate_rows('additional_issues', unit_key(row), [row])
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue  # Missing or corrupt details are repaired through the source.
        data = row['data']
        ident = data['source_id']
        if {k: v for k, v in data.items() if k != 'detail'} != current.get(ident):
            continue
        detail = data['detail']
        if ident in reusable and reusable[ident] != detail:
            conflicted.add(ident)
        reusable[ident] = detail
    return {ident: detail for ident, detail in reusable.items() if ident not in conflicted}


def previous_details(candidates):
    result = {}
    for row in candidates:
        try:
            result[row['record_key']] = validate(row['data'].get('detail'))
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
    return result


def attach_detail(c, row, detail, previous):
    if detail.get('availability') == 'unavailable':
        c.stats['details_unavailable'] = c.stats.get('details_unavailable', 0) + 1
        old = previous.get(row['record_key'])
        if old:
            last = old.get('last_available') if old.get('availability') == 'unavailable' else old
            if last:
                detail = {**detail, 'last_available': last}
    return {**row, 'data': {**row['data'], 'detail': detail}}
