"""The public darktrade protocol: actual date and complete pages are mandatory."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal

from empire.contracts.security import unified_code
from empire.features.graymarket.contract import (
    MAX_ROWS,
    PAGE_SIZE,
    day,
    number,
    source_time,
    validate,
    validate_row,
)

PAGE = "https://emrnweb.eastmoney.com/graymarket/home?appfenxiang=1"
URL = "https://quotederivates.eastmoney.com/datacenter/darktrade"
DOMAINS = ("eastmoney.com",)
HEADERS = {"rnProjectId": "emrn.GrayMarketRank", "Referer": PAGE}
REQUIRED = frozenset(("3", "4", "5", "6", "7", "8", "11", "13", "14", "16", "21"))
KNOWN = REQUIRED | {"9", "10", "12", "15", "19", "20"}


def params(stamp=None, page=1):
    if type(page) is not int or not 1 <= page <= MAX_ROWS // PAGE_SIZE:
        raise ValueError("资金榜页码超界")
    if stamp is None and page != 1:
        raise ValueError("资金榜后续分页必须固定日期")
    return dict(
        version=101,
        cver=100,
        date=day(stamp).replace("-", "") if stamp else "",
        StartPage=page,
        NumPerPage=PAGE_SIZE,
        sortflag=16,
        desc=1,
        market="",
        datetype="",
    )


def _date(value):
    if type(value) is not int or not re.fullmatch(r"\d{8}", str(value)):
        raise ValueError("资金榜实际日期无效")
    value = str(value)
    return day(value[:4] + "-" + value[4:6] + "-" + value[6:])


def _row(value):
    if not isinstance(value, dict) or not REQUIRED <= value.keys() or value.keys() - KNOWN:
        raise ValueError("资金榜字段缺失或来源结构改变")
    if type(value["3"]) is not int or value["3"] not in (0, 1):
        raise ValueError("资金榜来源市场尚未支持")
    raw_code = value["4"]
    # Eastmoney's market 0 also contains the BSE 920 code family. It is
    # a routing bucket, not a Shenzhen exchange identity.
    market = "SH"
    if value["3"] == 0:
        if not isinstance(raw_code, str) or not raw_code.startswith(("0", "3", "92")):
            raise ValueError("资金榜市场0证券代码族尚未核实")
        market = "BJ" if raw_code.startswith("92") else "SZ"
    code = unified_code(market, raw_code)
    if type(value["5"]) is not int or not 0 <= value["5"] <= 235959:
        raise ValueError("资金榜来源时间无效")
    raw_price = number(value["13"], integer_digits=18)
    row = [
        code,
        value["16"],
        *[number(value[k]) for k in ("6", "7", "8")],
        number(value["11"], scale=10, integer_digits=10),
        number(Decimal(raw_price) / 1000, scale=3, integer_digits=15),
        number(value["14"], scale=10, integer_digits=10),
        source_time(f"{value['5']:06d}"),
        value["21"],
    ]
    return validate_row(row)


@dataclass(frozen=True)
class SourcePage:
    date: str
    total: int
    number: int
    rows: list

    @property
    def pages(self):
        return (self.total + PAGE_SIZE - 1) // PAGE_SIZE


def parse(body, *, page=1, requested=None, through):
    params(requested, page)
    day(through)
    if not isinstance(body, dict) or type(body.get("errid")) is not int or body["errid"] != 0:
        raise ValueError("资金榜来源未返回有效数据；不能当作空日")
    stamp = _date(body.get("1"))
    if stamp > through or requested is not None and stamp != requested:
        raise ValueError("资金榜实际日期与请求不符或超前")
    total, values = body.get("2"), body.get("data")
    if type(total) is not int or not 1 <= total <= MAX_ROWS:
        raise ValueError("资金榜来源总数为空或超限")
    count = min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE)
    if not isinstance(values, list) or count <= 0 or len(values) != count:
        raise ValueError("资金榜页长与来源总数不符")
    rows = [_row(row) for row in values]
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError("资金榜页内证券重复")
    return SourcePage(stamp, total, page, rows)


def decode(raw, **kwargs):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("资金榜JSON字段重复")
            result[key] = value
        return result

    return parse(json.loads(raw, parse_float=Decimal, object_pairs_hook=unique_pairs), **kwargs)


class DayAssembly:
    """Reject missing, replayed or mixed pages before yielding any daily facts."""

    def __init__(self, first):
        if first.number != 1:
            raise ValueError("资金榜必须从第一页组装")
        self.date, self.total, self.pages = first.date, first.total, first.pages
        self.rows, self.keys, self.next_page = [], set(), 1
        self.add(first)

    def add(self, page):
        if (
            page.number != self.next_page
            or page.date != self.date
            or page.total != self.total
            or page.number > self.pages
        ):
            raise ValueError("资金榜分页缺失、乱序或日期/总数改变")
        keys = {row[0] for row in page.rows}
        if keys & self.keys:
            raise ValueError("资金榜跨页证券重复，拒绝去重掩盖遗漏")
        self.rows.extend(page.rows)
        self.keys.update(keys)
        self.next_page += 1

    def finish(self):
        if self.next_page != self.pages + 1 or len(self.rows) != self.total:
            raise ValueError("资金榜整日分页未收齐")
        return validate(sorted(self.rows, key=lambda row: row[0]))
