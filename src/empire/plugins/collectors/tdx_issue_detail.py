"""Fetch each required issue detail through the shared bounded downloader."""
import hashlib
import json

from empire.plugins.collectors.support import record_error_safely, wait_for_capacity
from empire.plugins.collectors.tdx_capital_source import PAGE_URL
from empire.plugins.datasets.capital_actions import unit_key, validate_rows
from empire.plugins.datasets.issue_detail import IssueSourceError, parse, validate

URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_xgzx_zfmx'


async def fetch_detail(c, row, aliases):
    await wait_for_capacity(c.ingest, c.stats)
    source_id = row['data']['source_id']
    response = await c.http.request('POST', URL,
        content=json.dumps({'Params': [source_id]}, separators=(',', ':')).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                 'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE_URL},
        allowed_domains=('tdx.com.cn',), project_id=c.project_id,
        policy=c.http.response_policy('generic'), max_retries=c.request_retries)
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
        response.close()


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


async def enrich(c, rows, aliases, cache, reusable=None, previous=None):
    result = []
    for row in rows:
        ident = row['data']['source_id']
        detail = cache.get(ident)
        if isinstance(detail, IssueSourceError):
            raise detail  # A code alias cannot fix an ID-only request in the same round.
        if detail is None and reusable is not None:
            detail = reusable.get(ident)
            if detail is not None:
                c.stats['details_reused'] = c.stats.get('details_reused', 0) + 1
        if detail is None:
            c.stats['details_requested'] = c.stats.get('details_requested', 0) + 1
            try:
                detail = await fetch_detail(c, row, aliases[ident])
            except IssueSourceError as exc:
                if len(aliases[ident]) > 1:
                    cache[ident] = exc
                raise
            # Only cross-security aliases need reuse; do not retain all detail bodies.
            if len(aliases[ident]) > 1:
                cache[ident] = detail
        if detail.get('availability') == 'unavailable':
            c.stats['details_unavailable'] = c.stats.get('details_unavailable', 0) + 1
            old = (previous or {}).get(row['record_key'])
            if old:
                last = old.get('last_available') if old.get('availability') == 'unavailable' else old
                if last:
                    detail = {**detail, 'last_available': last}
        result.append({**row, 'data': {**row['data'], 'detail': detail}})
    return result
