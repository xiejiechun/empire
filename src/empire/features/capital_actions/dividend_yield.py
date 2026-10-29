"""Explicit unavailable result after retirement of the required quote provider."""

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_scope import PreparationScope
from empire.features.capital_actions.distribution import distribution_result

PROBLEM = "开盘啦历史盘口功能已移除，缺少收盘价及逐日股本快照输入，区间现金股息率暂不可计算。"


async def calculate_yield(plugin, request):
    scope = PreparationScope.parse(request)
    result = distribution_result(scope, (CheckEvidence('fields', 'fail', PROBLEM),), {})
    result.update(
        id="dividend_yield",
        title="区间名义现金股息率",
        state="数据阻断",
        problem=PROBLEM,
        unit='%',
        formula='当前缺少已登记的收盘价格与逐日股本输入，不产生计算结果。',
        version='interval-nominal-dividend-yield-retired-v1',
    )
    return result


async def preparation_check(plugin, request=None):
    return (CheckEvidence("fields", "fail", PROBLEM),)
