"""Read-only source quality findings, independent of lossless collection validity."""
from decimal import Decimal

from empire.plugins.datasets.financial_statements import REQUIRED


def quality_issues(kind, row):
    fields = row['fields']
    issues = [dict(criterion='fields', message=f'来源未提供核心金额：{key}')
              for key in REQUIRED[kind] if fields.get(key) is None]
    if kind == 'balance':
        equations = [(REQUIRED[kind][0], REQUIRED[kind][1:])]
    elif kind == 'income':
        equations = [('*净利润', ('*归属于母公司所有者的净利润', '少数股东损益'))]
    else:
        equations = [('*现金及现金等价物净增加额', (
            '*经营活动产生的现金流量净额', '*投资活动产生的现金流量净额',
            '*筹资活动产生的现金流量净额', '四、汇率变动对现金及现金等价物的影响')),
            ('*期末现金及现金等价物余额', ('加：期初现金及现金等价物余额', '*现金及现金等价物净增加额'))]
    for total, parts in equations:
        values = [fields.get(key) for key in (total, *parts)]
        if any(v is None for v in values):
            continue  # Missing source values are not assumed to be zero.
        difference = abs(Decimal(values[0]['value']) - sum(Decimal(v['value']) for v in values[1:]))
        tolerance = sum(Decimal(v['resolution']) / 2 for v in values)
        if difference > tolerance:
            issues.append(dict(criterion='quality', message=(
                f'来源合计不符：{total}；差额 {difference:f} 元，舍入容差 {tolerance:f} 元')))
    return issues
