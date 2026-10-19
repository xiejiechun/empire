"""Source index identities and current member boundaries."""
import hashlib
import json
import re

from empire.contracts.security import index_code, unified_code

PROJECT = 'ths-indices'
JOB = PROJECT + '-v1'
BASE = 'https://q.10jqka.com.cn/zs/'
INDEX_LIMIT = 1000
MEMBER_LIMIT = 10000
MAX_RESPONSE_BYTES = 8 * 1024**2




def label(value, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('指数或证券名称无效')
    return value.strip()


def security_code(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9]{5,6}', value):
        raise ValueError('指数成员来源编号无效')
    return value


def member_identity(code):
    security_code(code)
    if len(code) != 6:
        return None
    venue = ('BJ' if code.startswith('92') or code[0] in '48' else
             'SH' if code[0] in '69' else 'SZ' if code[0] in '023' else None)
    return unified_code(venue, code) if venue else None


def members_url(code):
    return BASE + f'detail/code/{index_code(code)}/field/code/order/asc/page/1/size/10000/ajax/1/'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()
