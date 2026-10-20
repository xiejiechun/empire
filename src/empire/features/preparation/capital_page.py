"""Independent outputs from one capital.html response."""
from empire.features.preparation.definition import R
from empire.features.ths_capital.contract import REQUIREMENTS, SECTIONS

ITEMS = tuple(R(ident, SECTIONS[section], '公司行动' if section not in ('pledge', 'freeze') else '股东数据',
    '研究', '查询来源披露的' + SECTIONS[section], '页面来源记录及同锚点重复次数',
    '股票、公告日/报告期、主体及栏目结构化数值和完整详情；原事件与解除关联',
    '证券+栏目+业务锚点+同锚点序号', '当前完整响应全部栏目/期间和历史已保存记录',
    '空值、原币种、估算、重复次数保留；预计截止不等于实际解除',
    '每天18:30完整核验，最近3天确认', '报告期不是公告日；当前进展正文不提供严格历史版本回放',
    optional_fields='来源明确为空的金额、主体补充属性及日期；不补造未知值',
    boundary='只负责' + SECTIONS[section] + '的来源事实，不推断当前余额或上市以来完整历史')
    for section, ident in REQUIREMENTS.items())
