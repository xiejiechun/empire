"""Exact page protocol: latest date and one complete date without pagination."""

import re

from empire.features.industry_margin.contract import day, number, validate

PAGE = "http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_rzrq_rzrqhy.html"
URL = "http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_rzrq_hy"
COLUMNS = ["rqye", "T003", "T004", "T005", "T007", "T008", "T006", "hy"]


def params(stamp):
    return ["1", day(stamp).replace("-", "")] if stamp is not None else ["0", ""]


def parse(body, *, latest=False, through=None):
    if not isinstance(body, dict) or type(body.get("ErrorCode")) is not int or body["ErrorCode"]:
        raise ValueError("行业融资融券来源错误")
    sets = body.get("ResultSets")
    if not isinstance(sets, list) or len(sets) != 1 or not isinstance(sets[0], dict):
        raise ValueError("行业融资融券结果集契约改变")
    result = sets[0]
    rows = result.get("Content")
    if (
        result.get("ColName") != (["mxt"] if latest else COLUMNS)
        or not isinstance(rows, list)
        or type(result.get("Count")) is not int
        or result["Count"] != len(rows)
        or any(not isinstance(r, list) or len(r) != (1 if latest else 8) for r in rows)
    ):
        raise ValueError("行业融资融券列、集合或来源条数不符")
    if latest:
        if (
            len(rows) != 1
            or not isinstance(rows[0][0], str)
            or not re.fullmatch(r"\d{8}", rows[0][0])
        ):
            raise ValueError("行业融资融券最新日期无效")
        s = rows[0][0]
        stamp = day(s[:4] + "-" + s[4:6] + "-" + s[6:])
        if through is not None and stamp > through:
            raise ValueError("行业融资融券来源日期超前")
        return stamp
    return validate(
        sorted([[r[-1], *[number(v) for v in r[:-1]]] for r in rows], key=lambda r: r[0])
    )
