"""Public pure parser extracted without business-rule changes."""
from empire.contracts.collection_integrity import require_complete_set
from empire.features.capital_actions.contract import (
    ISSUE_COLUMNS,
    RIGHTS_COLUMNS,
    digest,
    ordered,
    source_row,
)
from empire.features.capital_actions.source_protocol import result_set


def parse(kind, body, capacity, report_date=None):
    if kind == 'dividends':
        from empire.features.capital_actions.dividend_parser import parse_period
        return parse_period(body, report_date, capacity)
    columns = {'additional_issues': ISSUE_COLUMNS, 'rights_issues': RIGHTS_COLUMNS}[kind]
    values = result_set(body, 0, columns)
    total = result_set(body, 2, ['count'])
    if len(total) != 1 or type(total[0][0]) is not int or total[0][0] < 0:
        raise ValueError('来源总数无效')
    total = total[0][0]
    columns_meta = ['ntype', 'page', 'cur'] if kind == 'additional_issues' else ['page', 'cur']
    metadata = result_set(body, 1, columns_meta)
    if len(metadata) != 1 or metadata[0][:-1] != ([0, 1] if kind == 'additional_issues' else [1]):
        raise ValueError('来源分页或栏目不匹配')
    from empire.features.capital_actions.fields import day
    day(metadata[0][-1], True)
    if len(values) >= capacity or total > len(values):
        raise ValueError('完整响应被截断或来源总数不符；禁止偏移分页补凑')
    raw = [dict(zip(columns, value, strict=True)) for value in values]
    rows = ordered([source_row(kind, value) for value in raw])
    require_complete_set(rows, len(rows), lambda row: row['record_key'])
    if kind == 'additional_issues':
        # A source issue can be joined to multiple historical security codes.
        groups = {}
        for row in rows:
            ident, data = row['data']['source_id'], row['data']
            if ident in groups and groups[ident] != data:
                raise ValueError('同一增发编号出现冲突业务内容')
            groups[ident] = data
        if len(groups) != total:
            raise ValueError('增发方案编号集合与来源总数不符')
    elif kind == 'rights_issues':
        # Count is source plans before the security-code alias join. Keep ALL aliases.
        if len({digest(row['data']) for row in rows}) != total:
            raise ValueError('配股方案与代码关联总数口径不符')
    return rows, total
