"""The single catalogue of independently deliverable collection and processing jobs."""
from empire.contracts.preparation_events import ITEMS as EVENTS
from empire.contracts.preparation_existing import ITEMS as EXISTING
from empire.contracts.preparation_foundation import ITEMS as FOUNDATION
from empire.contracts.preparation_markets import ITEMS as MARKETS
from empire.contracts.preparation_processing import ITEMS as PROCESSING

REQUIREMENTS = (*EXISTING, *FOUNDATION, *EVENTS, *MARKETS, *PROCESSING)
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
