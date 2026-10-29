"""The page's two modes, one request per necessary complete response."""

import json

from empire.features.hot_list.contract import (
    day,
    number,
    security,
    text_value,
    validate_dates,
    validate_detail,
)

PAGE = "http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_lhbd_ggxq.html"
URL = "http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_lhbd_ggxq"
DIRECTORY_COLUMNS = ["T001", "sweek", "scode"]
DETAIL_COLUMNS = [
    ["T004", "T012", "cjl", "cje", "closepri", "zdf"],
    [
        "T007",
        "T004",
        "T008",
        "T009",
        "T010",
        "je",
        "T012",
        "T006",
        "T011",
        "T015",
        "yxyz",
        "gsd",
        "bq1",
        "bq2",
        "bq3",
        "bq4",
    ],
    ["T002", "T007"],
    ["num"],
    ["T001", "T002", "T004", "T008", "T006", "T007", "mmbq"],
]


def params(code, requested=None):
    security(code)
    return ["0", code[:6], ""] if requested is None else ["1", code[:6], day(requested)]


def result_sets(body, columns):
    if (
        not isinstance(body, dict)
        or type(body.get("ErrorCode")) is not int
        or body["ErrorCode"] != 0
    ):
        raise ValueError(
            "通达信龙虎榜来源错误："
            + str(body.get("ErrorCode") if isinstance(body, dict) else "未知")
        )
    sets = body.get("ResultSets")
    if not isinstance(sets, list) or len(sets) != len(columns):
        raise ValueError("龙虎榜结果集缺失")
    output = []
    for value, names in zip(sets, columns, strict=True):
        rows = value.get("Content")
        if (
            value.get("ColName") != names
            or not isinstance(rows, list)
            or type(value.get("Count")) is not int
            or value["Count"] != len(rows)
        ):
            raise ValueError("龙虎榜列定义或来源条数不符")
        if any(not isinstance(r, list) or len(r) != len(names) for r in rows):
            raise ValueError("龙虎榜行字段缺失")
        output.append(rows)
    return output


def parse_directory(body, code, through):
    rows = result_sets(body, [DIRECTORY_COLUMNS])[0]
    dates = []
    for stamp, weekday, source_code in rows:
        if source_code != code[:6] or type(weekday) is not int or not 1 <= weekday <= 7:
            raise ValueError("龙虎榜日期目录证券或星期错误")
        dates.append(day(stamp))
    validate_dates(dates, through)
    return dates


def parse_detail(body):
    reasons, seats, counts, institutions, related = result_sets(body, DETAIL_COLUMNS)
    headers = [
        dict(
            reason_code=text_value(r[0], 32),
            reason=text_value(r[1], 1000),
            volume=number(r[2]),
            turnover=number(r[3]),
            close_price=number(r[4]),
            change_pct=number(r[5], pct=True),
        )
        for r in reasons
    ]
    entries = []
    for r in seats:
        entries.append(
            dict(
                reason_code=r[1],
                side=r[7],
                seat_rank=r[0],
                seat_name=r[2],
                buy_amount=number(r[3]),
                sell_amount=number(r[4]),
                net_amount=number(r[5]),
                extension=dict(
                    schema=1,
                    **dict(zip(("yxyz", "gsd", "bq1", "bq2", "bq3", "bq4"), r[10:], strict=True)),
                ),
            )
        )
        # A reason code may have multiple source summary variants. Each seat
        # must match one complete variant, without rounding or merging headers.
        matching = [h for h in headers if h["reason_code"] == r[1]]
        if not any(
            h["turnover"] == number(r[8]) and h["volume"] == number(r[9]) and h["reason"] == r[6]
            for h in matching
        ):
            raise ValueError("龙虎榜席位与原因的成交信息不一致")
    if len(institutions) != 1:
        raise ValueError("龙虎榜机构辅助次数结构改变")
    headers.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
    entries.sort(
        key=lambda r: (
            r["reason_code"],
            r["side"],
            r["seat_rank"],
            json.dumps(r, sort_keys=True, ensure_ascii=False),
        )
    )
    headers = [dict(seq=i, **r) for i, r in enumerate(headers, 1)]
    entries = [dict(seq=i, **r) for i, r in enumerate(entries, 1)]
    reason_keys, seat_keys = (
        {r["reason_code"] for r in headers},
        {r["reason_code"] for r in entries},
    )
    status = (
        "source_empty"
        if not entries
        else "present"
        if reason_keys == seat_keys and len(reason_keys) == len(headers)
        else "partial"
    )
    return validate_detail(
        dict(
            reasons=headers,
            seats=entries,
            status=status,
            auxiliary=dict(
                schema=1,
                counts=sorted(counts),
                institution_count=institutions[0][0],
                related=sorted(related),
            ),
        )
    )
