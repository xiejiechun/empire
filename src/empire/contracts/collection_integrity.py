"""Shared collection checks: a raw count cannot prove a unique business set."""
import json
from collections import Counter


def require_complete_set(rows, expected, identity):
    if type(expected) is not int or expected < 0:
        raise ValueError('来源总数无效')
    keys = [identity(row) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('来源业务键重复，不能以去重后的集合确认采集完整')
    if len(keys) != expected:
        raise ValueError(f'来源报告 {expected} 条，分页取得 {len(keys)} 条')
    return set(keys)


def confirmed_distinct_records(rows, repeated, identity):
    """Collapse source repetitions only after two complete multisets agree."""
    def contents(items):
        return Counter(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in items)
    if contents(rows) != contents(repeated):
        raise ValueError('来源业务键重复且完整响应复核不一致')
    unique = {}
    for row in rows:
        key = identity(row)
        if key in unique and unique[key] != row:
            raise ValueError('来源同一业务键内容冲突')
        unique[key] = row
    return list(unique.values())
