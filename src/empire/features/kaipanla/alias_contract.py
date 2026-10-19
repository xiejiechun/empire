"""Business-owned alias_contract; moved declarations retain existing behavior."""
import json
import re
from datetime import date


def validate_proof(proof, current, legacy):
    if (not isinstance(proof, dict)
            or set(proof) != {'source', 'current_code', 'legacy_code', 'isin', 'listing_date'}
            or proof['source'] != 'bse' or proof['current_code'] != current or proof['legacy_code'] != legacy
            or not isinstance(proof['isin'], str) or not re.fullmatch(r'CN[A-Z0-9]{10}', proof['isin'])
            or not isinstance(proof['listing_date'], str)):
        raise ValueError('北交所历史代码缺少明确证券身份映射证明')
    date.fromisoformat(proof['listing_date'])
    return proof


def parse_alias(body, current, legacy, listed):
    match = re.fullmatch(r'securityMasterCallback\((.*)\)\s*;?', body.strip(), re.S)
    if not match:
        raise ValueError('北交所代码核实响应不是现行 JSONP 契约')
    payload = json.loads(match.group(1))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError('北交所代码核实结构无效')
    page = payload[0]
    records = page.get('content')
    if page.get('totalElements') != 1 or not isinstance(records, list) or len(records) != 1:
        raise ValueError('北交所旧代码查不到唯一当前证券，不能放行错配响应')
    row = records[0]
    if not isinstance(row, dict):
        raise ValueError('北交所证券身份记录结构无效')
    if (row.get('xxzqdm') != current or str(row.get('xxfcbj')) != '2'
            or row.get('fxssrq') != date.fromisoformat(listed).strftime('%Y%m%d')):
        raise ValueError('北交所旧代码对应的当前证券或上市日与请求范围不同')
    return validate_proof(dict(source='bse', current_code=current, legacy_code=legacy,
                              isin=row.get('xxisin'), listing_date=listed), current, legacy)
