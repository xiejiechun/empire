"""Independent daily pools and reason outputs; no coupled completion labels."""
from empire.features.preparation.definition import R

ITEMS = tuple(R('yuanhang_' + kind, '远航版' + title, '涨跌停分析', 'P1',
    '日频市场情绪、涨跌停成员和原因研究', '证券日原因' if kind == 'reason' else '日期池完整集合',
    '交易日、统一证券身份、原名称及来源字段；NULL不填0',
    '(交易日,证券)' if kind == 'reason' else '(交易日,池,证券)',
    '来源可查询历史逐交易日补齐，未知空响应不证明最早边界',
    '完整业务键及内容摘要一致；错误、缺页不能成为空成功',
    ('每日18:00维护；近期5交易日及20交易日历史轮转，分批补缺' if kind == 'reason'
     else '15:30后日终核验；近期5交易日及20交易日历史轮转；盘中Redis采样不作为日终完整性证明'),
    '日终数据用于下一可交易日；原因无可靠公布时刻，不支持历史原因选股回放',
    boundary='本项独立检查来源集合与内容；其他池或原因完成不代替本项。')
    for kind, title in (('limit_up_pool', '涨停板'), ('sprint_limit_up', '涨停冲刺'),
        ('connect_broad_pool', '连板池'), ('open_limit_up_pool', '炸板池'),
        ('limit_down_pool', '跌停板'), ('reason', '历史涨跌停原因')))
