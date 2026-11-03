"""One request per necessary page on shared routing and bounded buffers."""
import json
from decimal import Decimal
from functools import partial
from urllib.parse import urlencode

from empire.features.yuanhang_limits.contract import (
    BASE_URL,
    DOMAIN,
    FILTER,
    MAX_UNIT_BYTES,
    PAGE_SIZE,
    REQUEST_FIELDS,
    day_value,
    pool_value,
)
from empire.features.yuanhang_limits.model import SourceTimeDateError, parse_page, parse_reason
from empire.sources.security_identity import resolve_identity


def earlier_pool_time(response, *, day, page):
    """Only an explicitly detected earlier epoch is eligible for live retry."""
    try:
        parse_page(json.loads(response.content, parse_float=Decimal), day, page)
    except SourceTimeDateError as exc:
        return exc.source_metadata['source_date'] < day
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, OSError):
        pass
    return False


async def fetch_pool(http, pool, day, *, project_id, max_retries=1, reservation=None,
                     identity_resolver=None, retry_earlier_time=False):
    pool_value(pool)
    day_value(day)
    policy = http.response_policy('generic')
    rows, total, pages, received, wire_bytes = [], None, 1, 0, 0
    auxiliary = dict(requests=0, response_bytes=0, wire_bytes=0)
    page = 1
    while page <= pages:
        params = dict(strategy=pool, filter=FILTER, date=day.replace('-', ''),
                      field=REQUEST_FIELDS, orderField='code', orderType='1',
                      limit=PAGE_SIZE, page=page)
        response = await http.request('GET', BASE_URL + 'change-table?' + urlencode(params),
            allowed_domains=(DOMAIN,), project_id=project_id, max_redirects=0,
            headers={'Referer': 'PC_Hevo_FocusLimitUp_ChangeGridWidget'},
            policy=policy, reservation=reservation, max_retries=max_retries,
            strip_credentials=True,
            retry_response=partial(earlier_pool_time, day=day, page=page) if retry_earlier_time else None)
        try:
            received += len(response.content)
            actual_wire = getattr(response, 'extensions', {}).get('download', {}).get('wire_bytes')
            wire_bytes = wire_bytes + actual_wire if wire_bytes is not None and type(actual_wire) is int else None
            # One unit's retained pages fit inside its prefetch reservation.
            if len(response.content) > policy.max_body_bytes or received > MAX_UNIT_BYTES:
                raise ValueError('完整日期池超过共享单元预算，未发布半成品')
            obj = json.loads(response.content, parse_float=Decimal)
            identities = {}
            if identity_resolver and isinstance(obj, dict) and isinstance(obj.get('data'), dict):
                members = obj['data'].get('data')
                if isinstance(members, list):
                    codes = {r.get('code') for r in members if isinstance(r, dict)
                             and r.get('market_id') is None and r.get('market_type') == 'HS'}
                    if codes:
                        identities = await identity_resolver(codes)
                        for row in members:
                            code = row.get('code') if isinstance(row, dict) else None
                            if code in codes and code not in identities:
                                symbol = await resolve_identity(http, code, project_id=project_id,
                                    source_name=row.get('name'), reservation=reservation, metrics=auxiliary)
                                identities[code] = (symbol, 'sina_lookup')
            values, count, page_count = parse_page(obj, day, page, identities=identities)
            if total is not None and (total != count or pages != page_count):
                raise ValueError('涨停分析跨页总量改变')
            if rows and values and rows[-1]['unified_code'][:6] >= values[0]['unified_code'][:6]:
                raise ValueError('涨停分析跨页排序重复或倒序')
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, OSError) as exc:
            # An auxiliary identity lookup may already own the failing response.
            if not getattr(exc, 'source_diagnostic', None):
                exc.source_metadata = {**getattr(exc, 'source_metadata', {}),
                                       'trade_date': day, 'pool_type': pool, 'page': page}
                exc.source_diagnostic = dict(request_url=str(response.url), status_code=response.status_code,
                                             raw_body=response.content, metadata=exc.source_metadata)
            raise
        finally:
            response.close()
        rows.extend(values)
        total, pages = count, page_count
        page += 1
    if len(rows) != total or len({r['unified_code'] for r in rows}) != total:
        raise ValueError('涨停分析完整成员集合不符')
    return {'trade_date': day, 'pool_type': pool, 'filter': FILTER,
            'rows': rows, 'source_total': total, 'requests': page - 1 + auxiliary['requests'],
            'response_bytes': received + auxiliary['response_bytes'],
            'wire_bytes': wire_bytes + auxiliary['wire_bytes']
                if wire_bytes is not None and auxiliary['wire_bytes'] is not None else None}


def transient_reason_failure(response, *, code=None, day=None):
    """Retry the observed -1/fail with valid columns; never accept its data."""
    try:
        obj = json.loads(response.content)
    except (ValueError, UnicodeError):
        return False
    known = (isinstance(obj, dict) and type(obj.get('status_code')) is int
            and obj['status_code'] == -1 and obj.get('status_msg') == 'fail'
            and isinstance(obj.get('data'), dict)
            and set(obj['data']) == {'reasonrevealedList', 'reasonKindList'})
    if not known:
        return False
    if all(value is None or value == [] for value in obj['data'].values()):
        return True
    if code is None or day is None:
        return False
    try:
        parse_reason({**obj, 'status_code': 0}, code, day)
    except (ValueError, TypeError, KeyError):
        return False
    return True


async def fetch_reason(http, code, day, *, project_id, max_retries=1, reservation=None):
    from empire.contracts.security import split_unified_code
    split_unified_code(code)
    day_value(day)
    params = dict(indexCode=code, startTime=day.replace('-', ''), endTime=day.replace('-', ''))
    response = await http.request('GET', BASE_URL + 'single_stock_analysis?' + urlencode(params),
        allowed_domains=(DOMAIN,), project_id=project_id, max_redirects=0,
        headers={'Referer': 'PC_Hevo_FocusLimitUp_IndividualStockAnalysisWidget'},
        policy=http.response_policy('generic'), reservation=reservation,
        max_retries=max_retries, strip_credentials=True,
        retry_response=partial(transient_reason_failure, code=code, day=day))
    try:
        result = parse_reason(json.loads(response.content), code, day)
        return {**result, 'requests': 1, 'response_bytes': len(response.content),
                'wire_bytes': getattr(response, 'extensions', {}).get('download', {}).get('wire_bytes')}
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        exc.source_metadata = {**getattr(exc, 'source_metadata', {}),
                               'unified_code': code, 'trade_date': day}
        exc.source_diagnostic = dict(request_url=str(response.url), status_code=response.status_code,
                                     raw_body=response.content, metadata=exc.source_metadata)
        raise
    finally:
        response.close()
