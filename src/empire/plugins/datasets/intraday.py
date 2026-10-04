"""Legacy pair validation used only by explicit migration; no runtime dataset."""
import hashlib
import json
import re
from datetime import date, datetime

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import CHINA
from empire.plugins.collectors.kaipanla_alias import validate_proof
from empire.plugins.collectors.kaipanla_source import combine_day, parse_response

PROJECT = 'kaipanla-intraday'
JOB = PROJECT + '-v1'
DATASETS = {'intraday.day'}
FINGERPRINT_NAMESPACE = 'kaipanla_intraday_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'stock_intraday': {'unified_code', 'trade_date', 'payload',
                            'content_hash', 'version_observed_at'}}
KEYS = {'stock_intraday': ['unified_code', 'trade_date']}
FIELDS = {'code', 'trade_date', 'preclose_px', 'trend', 'auction', 'source_times', 'market', 'lifecycle',
          'source_codes', 'aliases'}


def identity(row):
    return row['market'] + ':' + row['code'] + ':' + row['trade_date']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate(row):
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise ValueError('分时证券日字段无效')
    code, market = row['code'], row['market']
    if (not isinstance(code, str) or not re.fullmatch('[0-9]{6}', code)
            or market not in ('SH', 'SZ', 'BJ')):
        raise ValueError('分时证券身份无效')
    day = date.fromisoformat(row['trade_date'])
    if not date(2021, 1, 1) <= day <= datetime.now(CHINA).date() or day.isoformat() != row['trade_date']:
        raise ValueError('分时日期超出支持范围')
    life = row['lifecycle']
    if (not isinstance(life, dict) or set(life) != {'listing_date', 'listing_source', 'market_start'}
            or life['listing_source'] != 'eastmoney'
            or day < max(date.fromisoformat(life['listing_date']), date.fromisoformat(life['market_start']))):
        raise ValueError('分时上市日期或市场生命周期关联无效')
    stamps = row['source_times']
    if not isinstance(stamps, list) or len(stamps) != 2:
        raise ValueError('分时两个来源时间必需保存')
    source_codes, aliases = row['source_codes'], row['aliases']
    if (not isinstance(source_codes, list) or len(source_codes) != 2
            or any(not isinstance(c, str) or not re.fullmatch('[0-9]{6}', c) for c in source_codes)
            or not isinstance(aliases, dict) or set(aliases) != set(source_codes) - {code}):
        raise ValueError('分时来源代码与旧代码证明关联无效')
    for legacy, proof in aliases.items():
        validate_proof(proof, code, legacy)
        if market != 'BJ' or proof['listing_date'] != life['listing_date']:
            raise ValueError('旧代码不能跨市场或上市身份放行')
    parts = []
    for i, kind in enumerate(('trend', 'auction')):
        payload = dict(errcode='0', code=source_codes[i], day=day.strftime('%Y%m%d'),
                       preclose_px=row['preclose_px'], time=stamps[i])
        payload['trend' if kind == 'trend' else 'bid'] = row[kind]
        parts.append(parse_response(payload, code, day, kind, aliases))
    combine_day(*parts)
    return row
