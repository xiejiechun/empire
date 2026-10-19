"""The single catalogue of independently deliverable collection and processing jobs."""
from empire.features.preparation.capital_page import ITEMS as CAPITAL_PAGE
from empire.features.preparation.events import ITEMS as EVENTS
from empire.features.preparation.existing import ITEMS as EXISTING
from empire.features.preparation.foundation import ITEMS as FOUNDATION
from empire.features.preparation.markets import ITEMS as MARKETS
from empire.features.preparation.processing import ITEMS as PROCESSING

REQUIREMENTS = (*EXISTING, *FOUNDATION, *EVENTS, *CAPITAL_PAGE, *MARKETS, *PROCESSING)
BY_ID = {item.id: item for item in REQUIREMENTS}
if len(BY_ID) != len(REQUIREMENTS):
    raise ValueError('数据准备项目 ID 重复')
for item in REQUIREMENTS:
    if not item.boundary or item.kind not in {'采集', '整理', '计算', '核对'}:
        raise ValueError('每个项目必须写明工作类型和独立边界')
    if item.kind == '采集' and item.dependencies:
        raise ValueError('采集项目不能把其他数据项目的完成当作自身完成条件；跨数据检查应单列')
    if any(dep not in BY_ID for dep in (*item.dependencies, *item.related)):
        raise ValueError('数据准备项目引用了不存在的项目')


def _visit(ident, seen):
    if ident in seen:
        raise ValueError('数据准备项目存在循环依赖')
    for dep in BY_ID[ident].dependencies:
        _visit(dep, seen | {ident})


for item in REQUIREMENTS:
    _visit(item.id, set())
