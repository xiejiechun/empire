"""Explicit per-run scope on the existing collector, never a saved task policy."""

from datetime import date

from empire.contracts.security import split_unified_code


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {
        "securities",
        "start",
        "end",
        "proxy_priority",
    }:
        raise ValueError("有限采集须明确证券、起止日期和临时代理策略")
    securities = value["securities"]
    if (
        not isinstance(securities, list)
        or not 1 <= len(securities) <= 50
        or len(set(securities)) != len(securities)
        or type(value["proxy_priority"]) is not bool
    ):
        raise ValueError("有限采集证券须为1～50个唯一市场代码")
    for security in securities:
        split_unified_code(security)
    lower, upper = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    if (
        lower.isoformat() != value["start"]
        or upper.isoformat() != value["end"]
        or lower < date(2021, 1, 1)
        or lower > upper
        or (upper - lower).days > 3660
    ):
        raise ValueError("有限采集范围须为2021年起有序闭区间，最多3660日")
    return {**value, "securities": sorted(securities)}


def select_plan(request, stocks, days):
    request = validate_request(request)
    wanted = set(request["securities"])
    selected = [s for s in stocks if s["code"] + "." + s["market"] in wanted]
    if {s["code"] + "." + s["market"] for s in selected} != wanted:
        raise ValueError("有限采集证券不在已核验正式股票池")
    if not days or date.fromisoformat(request["end"]) > days[-1]:
        # Non-trading end dates may follow the last closed trading day.
        # The caller's plan has already verified the current official calendar.
        from datetime import datetime

        from empire.core.time import CHINA

        if date.fromisoformat(request["end"]) >= datetime.now(CHINA).date():
            raise ValueError("有限采集截止日包含尚未结束范围")
    selected_days = [d for d in days if request["start"] <= d.isoformat() <= request["end"]]
    if not selected_days:
        raise ValueError("有限采集范围没有已结束交易日")
    return selected, selected_days
