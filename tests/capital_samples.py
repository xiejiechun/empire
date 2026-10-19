"""Synthetic source fixtures, independent of live business records."""
from empire.features.capital_actions.contract import ISSUE_COLUMNS, RIGHTS_COLUMNS
from empire.features.capital_actions.dividend_parser import COLUMNS

STOCK = dict(market='SH', code='688110', name='测试证券')


def issue_detail(body=None):
    from empire.features.capital_actions.issue_contract import COLUMNS
    body = body or source('additional_issues')
    raw = dict(zip(ISSUE_COLUMNS, body['ResultSets'][0]['Content'][0], strict=True))
    values = {key: raw.get(key) for key in COLUMNS}
    values.update(T049='测试增发', T044='2026-01-02', T055=1, T057=2, T026=60,
        T102='2026-01-03 00:00:00', T052=2.5, T104=-0.2, T024=3.5, cT012='测试承销商',
        T111='余额包销', T109='符合条件的投资者', T017='询价发行',
        OpenPrice=11, ClosePrice=12, kpzdf=10, spzdf=20)
    return dict(ErrorCode=0, ResultSets=[dict(Count=1, ColName=COLUMNS,
                                           Content=[[values[k] for k in COLUMNS]])])


def with_issue_detail(rows, body=None):
    from empire.features.capital_actions.issue_contract import parse
    for row in rows:
        row['data']['detail'] = parse(issue_detail(body), row, {'688110', row['code']})
    return rows


def source(kind, *, code='688110', amount=6, total=None, rows=None):
    if kind == 'dividends':
        columns = list(COLUMNS)
        values = ['source-id', code, '测试证券', 1, 0, 4.9, 4.9, amount, 1.5, 9.3, 7.8, 0.5,
                  '2026-04-20', '2026-06-01', '2026-06-02', '实施方案']
        metadata = (['page', 'nzt', 'nflag', 'strjzr'], [1, 0, 0, '2025-12-31'])
    elif kind == 'additional_issues':
        columns = list(ISSUE_COLUMNS)
        values = [1, code, '测试证券', 6, amount, 100, 106, None, None, 10, 20,
                  None, '2026-01-01', '2026-01-01', '2026-02-01', 1001, '定向增发']
        metadata = (['ntype', 'page', 'cur'], [0, 1, '2026-09-30'])
    else:
        columns = list(RIGHTS_COLUMNS)
        values = [1, 3, amount, '2026-01-01', '2026-01-09', '2026-01-02', '2026-01-08',
                  30, 100, 130, '700001', '2026-02-01', code, '测试证券', 20]
        metadata = (['page', 'cur'], [1, '2026-09-30'])
    rows = [values] if rows is None else rows
    def result(columns, content):
        return dict(Count=len(content), ColName=columns, Content=content)
    return dict(ErrorCode=0, ResultSets=[result(columns, rows), result(metadata[0], [metadata[1]]),
                result(['count'], [[len(rows) if total is None else total]])])
