"""Business-owned canonical; moved declarations retain existing behavior."""
import hashlib
import json


def identity(row):
    return row['market'] + ':' + row['code'] + ':' + row['trade_date']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
