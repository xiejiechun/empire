"""The page's exact seven parameters; no hidden per-page or per-day requests."""

import json
import re

from empire.features.margin.contract import CAPACITY, number, security, validate

PAGE = "http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_rzrq_rzrqggmx.html"
URL = "http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_rzrq_gg"
COLUMNS = ["bt009", "bt010", "ClosePrice", "T001", "T003", "T004", "T006", "T007"]


def params(code):
    security(code)
    return ["2", "1", code[:6], "", "1", "1", str(CAPACITY)]


def transient_query_timeout(response):
    """Retry only the observed backend timeout without business result sets."""
    try:
        body = json.loads(response.content)
    except (ValueError, UnicodeError):
        return False
    return (
        isinstance(body, dict)
        and type(body.get("ErrorCode")) is int
        and body["ErrorCode"] == -1009
        and body.get("ErrorInfo") == "cache语句执行超时"
        and body.get("ResultSets") in (None, [])
    )


def parse(body, through):
    if (
        not isinstance(body, dict)
        or type(body.get("ErrorCode")) is not int
        or body["ErrorCode"] != 0
    ):
        code = body.get("ErrorCode") if isinstance(body, dict) else "未知"
        reason = (
            "（来源服务端cache语句执行超时）"
            if isinstance(body, dict)
            and type(code) is int
            and code == -1009
            and body.get("ErrorInfo") == "cache语句执行超时"
            else ""
        )
        raise ValueError(f"融资融券来源错误：{code}{reason}，不能解释为空记录")
    sets = body.get("ResultSets")
    if not isinstance(sets, list) or len(sets) != 3:
        raise ValueError("融资融券完整性结果集缺失")
    output = []
    for result, names in zip(sets, (COLUMNS, ["page"], ["count"]), strict=True):
        if (
            not isinstance(result, dict)
            or result.get("ColName") != names
            or not isinstance(result.get("Content"), list)
            or type(result.get("Count")) is not int
            or result["Count"] != len(result["Content"])
            or any(not isinstance(r, list) or len(r) != len(names) for r in result["Content"])
        ):
            raise ValueError("融资融券列或条数契约改变")
        output.append(result["Content"])
    raw, page, total = output
    if (
        page != [[1]]
        or type(page[0][0]) is not int
        or len(total) != 1
        or type(total[0][0]) is not int
        or total[0][0] != len(raw)
        or len(raw) > CAPACITY
    ):
        raise ValueError("融资融券页码、总数或10000条完整响应不符")
    rows = []
    for row in raw:
        stamp = row[3]
        if not isinstance(stamp, str) or not re.fullmatch(r"\d{8}", stamp):
            raise ValueError("融资融券来源日期无效")
        rows.append(
            [
                stamp[:4] + "-" + stamp[4:6] + "-" + stamp[6:],
                *[number(v, optional=i < 3) for i, v in enumerate((*row[:3], *row[4:]))],
            ]
        )
    return validate(rows, through)
