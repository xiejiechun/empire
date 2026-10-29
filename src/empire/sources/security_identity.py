"""Exact source-symbol lookup for identities absent from the current stock list."""
import re

from empire.contracts.security import unified_code

URL = 'https://suggest3.sinajs.cn/suggest/'


def parse_identity(body, code, *, source_name=None):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('身份核实代码无效')
    # The provider also returns indices under type 11. An exact code can have
    # several market symbols; the source company label may disambiguate them.
    if not isinstance(body, bytes) or len(body) > 65536:
        raise ValueError('身份核实响应超限')
    match = re.fullmatch(rb'\s*var themeIdentity="([^"\r\n]*)";\s*', body)
    if not match:
        raise ValueError('身份核实响应结构改变')
    matches, named = set(), set()
    for record in match[1].split(b';'):
        if not record:
            continue
        parts = record.split(b',')
        if len(parts) != 12:
            raise ValueError('身份核实证券字段改变')
        if parts[2] != code.encode('ascii'):
            continue
        symbol = parts[3].decode('ascii')
        if parts[1] != b'11' or not re.fullmatch(r'(sh|sz|bj)' + code, symbol):
            raise ValueError('精确证券的市场标记无效')
        identity = unified_code(symbol[:2].upper(), code)
        matches.add(identity)
        try:
            label = parts[4].decode('gb18030')
        except UnicodeDecodeError as exc:
            raise ValueError('身份核实证券名称编码错误') from exc
        if source_name is not None and label == source_name:
            named.add(identity)
    if len(matches) > 1 and len(named) == 1:
        return named.pop()
    if len(matches) != 1:
        raise ValueError(f'来源证券{code}没有唯一精确市场证据，不能用关联搜索结果代替')
    return matches.pop()


async def resolve_identity(http, code, *, project_id, source_name=None, reservation=None, metrics=None):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('身份核实代码无效')
    response = await http.request('GET', URL + 'type=11&key=' + code + '&count=50&name=themeIdentity',
        headers={'Referer': 'https://finance.sina.com.cn/'}, allowed_domains=('sinajs.cn',),
        project_id=project_id, policy=http.response_policy('generic'), max_retries=1,
        max_redirects=0, strip_credentials=True, reservation=reservation)
    try:
        if metrics is not None:
            metrics['requests'] = metrics.get('requests', 0) + 1
            metrics['response_bytes'] = metrics.get('response_bytes', 0) + len(response.content)
            wire = getattr(response, 'extensions', {}).get('download', {}).get('wire_bytes')
            metrics['wire_bytes'] = metrics.get('wire_bytes', 0) + wire if type(wire) is int and metrics.get('wire_bytes', 0) is not None else None
        return parse_identity(response.content, code, source_name=source_name)
    finally:
        response.close()
