"""Verify historical header aliases through the exchange's exact security lookup."""
import hashlib

from empire.features.kaipanla.alias_contract import parse_alias
from empire.plugins.collectors.support import record_error_safely

URL = 'https://www.bse.cn/nqxxController/nqxxCnzq.do'


async def resolve(collector, current, legacy, listed):
    cache = getattr(collector, 'aliases', None)
    if cache is None:
        collector.aliases = cache = {}
    key = (current, legacy, listed)
    if key in cache:
        return cache[key]
    response = await collector.http.request('POST', URL, allowed_domains=('bse.cn',),
        project_id=collector.project_id, policy=collector.http.response_policy('generic'),
        max_retries=collector.request_retries, max_redirects=0,
        params={'callback': 'securityMasterCallback'},
        data=dict(page='0', typejb='T', **{'xxfcbj[]': '2'}, xxzqdm=legacy,
                  sortfield='xxzqdm', sorttype='asc'),
        headers={'Accept': '*/*', 'Origin': 'https://www.bse.cn',
                 'Referer': 'https://www.bse.cn/nq/listedcompany.html', 'User-Agent': 'Mozilla/5.0'})
    try:
        proof = parse_alias(response.content.decode('utf-8'), current, legacy, listed)
    except (ValueError, TypeError, KeyError) as exc:
        body = response.content
        exc.diagnostic_recorded = await record_error_safely(collector.records, collector.stats,
            collector.project_id, exc, stage='source_alias', unavailable_message='代码核实错误样本暂未写入 Redis',
            fields=dict(request_url=URL, status_code=response.status_code, raw_body=body[:65536],
                observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
                metadata=dict(current=current, legacy=legacy)))
        raise
    finally:
        response.close()
    cache[key] = proof
    return proof
