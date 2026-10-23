"""Exact source-symbol lookup for identities absent from the current stock list."""
import re

from empire.contracts.security import unified_code
from empire.features.themes.detail_model import DetailError

URL = 'https://suggest3.sinajs.cn/suggest/'


def parse_identity(body, code):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise DetailError('身份核实代码无效')
    # Only ASCII identity columns are interpreted. Company labels may use the
    # provider's encoding; they never identify a market or replace an old code.
    if not isinstance(body, bytes) or len(body) > 65536:
        raise DetailError('身份核实响应超限')
    match = re.fullmatch(rb'\s*var themeIdentity="([^"\r\n]*)";\s*', body)
    if not match:
        raise DetailError('身份核实响应结构改变')
    matches = set()
    for record in match[1].split(b';'):
        if not record:
            continue
        parts = record.split(b',')
        if len(parts) != 12:
            raise DetailError('身份核实证券字段改变')
        if parts[2] != code.encode('ascii'):
            continue
        symbol = parts[3].decode('ascii')
        if parts[1] != b'11' or not re.fullmatch(r'(sh|sz|bj)' + code, symbol):
            raise DetailError('精确证券的市场标记无效')
        matches.add(unified_code(symbol[:2].upper(), code))
    if len(matches) != 1:
        raise DetailError('来源证券没有唯一精确市场证据，不能用关联搜索结果代替')
    return matches.pop()


async def resolve_identity(http, code, *, project_id, reservation=None):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise DetailError('身份核实代码无效')
    response = await http.request('GET', URL + 'type=11,12&key=' + code + '&name=themeIdentity',
        headers={'Referer': 'https://finance.sina.com.cn/'}, allowed_domains=('sinajs.cn',),
        project_id=project_id, policy=http.response_policy('generic'), max_retries=1,
        max_redirects=0, strip_credentials=True, reservation=reservation)
    try:
        return parse_identity(response.content, code)
    finally:
        response.close()
