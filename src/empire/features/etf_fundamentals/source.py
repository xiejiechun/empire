"""Strict page envelopes and the seven published Eastmoney columns."""

import json
import re
from decimal import Decimal

from empire.features.etf_fundamentals.contract import (
    NAV_FIELDS,
    bounded_text,
    day,
    number,
    validate_nav,
    validate_share,
)

SSE_URL = "https://query.sse.com.cn/commonQuery.do"
SZSE_URL = "https://www.szse.cn/api/report/ShowReport"
NAV_URL = "https://api.fund.eastmoney.com/f10/lsjz"
PAGES = dict(
    sse="https://www.sse.com.cn/market/funddata/volumn/etfvolumn/",
    szse="https://www.szse.cn/market/fund/volume/etf/index.html",
    ttjj="https://fundf10.eastmoney.com/jjjz_{code}.html",
)
SQL_IDS = dict(
    etf="COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
    money="COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L",
)


def document(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("ETF来源未返回合法JSON") from exc


def integer(value, maximum=100000):
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch("[0-9]+", value):
        result = int(value)
    else:
        raise ValueError("ETF分页整数无效")
    if not 0 <= result <= maximum:
        raise ValueError("ETF分页上限无效")
    return result


def sse_params(stamp, group, page=1):
    return dict(
        sqlId=SQL_IDS[group],
        STAT_DATE=day(stamp),
        isPagination="true",
        **{
            "pageHelp.pageSize": 1000,
            "pageHelp.pageNo": page,
            "pageHelp.beginPage": page,
            "pageHelp.endPage": page,
            "pageHelp.cacheSize": 1,
        },
    )


def sse_page(raw, stamp, group, page):
    d = document(raw)
    if (
        any(d.get(k) for k in ("actionErrors", "actionMessages", "fieldErrors"))
        or d.get("sqlId") != SQL_IDS[group]
    ):
        raise ValueError("上交所ETF接口错误或查询身份不符")
    h, records = d["pageHelp"], d["result"]
    total, size = integer(h["total"], 5000), integer(h["pageSize"], 1000)
    pages = (total + size - 1) // size if size else -1
    if size != 1000 or integer(h["pageNo"]) != page or integer(h["pageCount"]) != pages:
        raise ValueError("上交所ETF分页元数据无效")
    expected = min(size, max(0, total - (page - 1) * size))
    if not isinstance(records, list) or len(records) != expected:
        raise ValueError("上交所ETF分页缺行")
    rows = []
    for r in records:
        if day(r["STAT_DATE"]) != stamp or not re.fullmatch("[0-9]{6}", r["SEC_CODE"]):
            raise ValueError("上交所ETF日期或代码不符")
        amount = number(r["TOT_VOL"])
        if amount is None:
            raise ValueError("上交所ETF总份额缺失")
        rows.append(
            [
                r["SEC_CODE"] + ".SH",
                bounded_text(r["SEC_NAME"], 128, required=True),
                number(Decimal(amount) * 10000),
                group,
                bounded_text(r.get("ETF_TYPE"), 64),
            ]
        )
    return total, pages, rows


def szse_params(stamp, kind="JSON"):
    return dict(
        SHOWTYPE=kind, CATALOGID="scsj_fund_jjgm", jjlb="ETF", txtStart=day(stamp), txtEnd=stamp
    )


def szse_head(raw, stamp):
    result = document(raw)
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("深交所ETF报告身份无效")
    d = result[0]
    h = d["metadata"]
    total = integer(h["recordcount"], 5000)
    if (
        d.get("error")
        or h["catalogid"] != "scsj_fund_jjgm"
        or integer(h["pageno"]) != 1
        or integer(h["pagesize"]) != 20
    ):
        raise ValueError("深交所ETF报告错误或分页元数据无效")
    if integer(h["pagecount"]) != (total + 19) // 20 or len(d["data"]) != min(total, 20):
        raise ValueError("深交所ETF首页数量无效")
    rows = {}
    for r in d["data"]:
        code = r["fund_code"].strip()
        if r["size_date"] != stamp or not re.fullmatch("[0-9]{6}", code) or code + ".SZ" in rows:
            raise ValueError("深交所ETF首页日期或身份无效")
        rows[code + ".SZ"] = number(r["current_size"].replace(",", ""))
    return total, rows


def optional_number(value):
    return None if value in (None, "", "--", "---") else number(value)


def nav_page(raw, code, first, last, page):
    d = document(raw)
    if d.get("ErrCode") != 0 or not isinstance(d.get("Data"), dict):
        raise ValueError("天天基金无合法数据对象，不能判作源端空历史")
    h, records = d["Data"], d["Data"].get("LSJZList")
    total = integer(d["TotalCount"], 20000)
    if (
        integer(d["PageIndex"]) != page
        or integer(d["PageSize"]) != 20
        or not isinstance(records, list)
    ):
        raise ValueError("天天基金分页身份无效")
    if len(records) != min(20, max(0, total - (page - 1) * 20)):
        raise ValueError("天天基金分页缺行")
    fund_type = bounded_text(h["FundType"], 16, required=True)
    label = bounded_text(h.get("SYType"), 64)
    kind = "income" if fund_type in ("004", "005") and code[:6] != "511880" else "nav"
    rows, previous = [], "9999-12-31"
    for r in records:
        if not {"FSRQ", "DWJZ", "LJJZ", "JZZZL", "SGZT", "SHZT", "FHSP"} <= r.keys():
            raise ValueError("天天基金完整七列缺失")
        stamp = day(r["FSRQ"])
        if not first <= stamp <= last or stamp >= previous:
            raise ValueError("天天基金日期越界、重复或乱序")
        values = dict(
            value_kind=kind,
            unit_nav=optional_number(r["DWJZ"]) if kind == "nav" else None,
            accumulated_nav=optional_number(r["LJJZ"]) if kind == "nav" else None,
            daily_change_pct=optional_number(r["JZZZL"]),
            income_value=optional_number(r["DWJZ"]) if kind == "income" else None,
            yield_7d_pct=optional_number(r["LJJZ"]) if kind == "income" else None,
            income_basis_shares=None,
            currency=None,
            purchase_status=bounded_text(r["SGZT"], 64),
            redemption_status=bounded_text(r["SHZT"], 64),
            distribution_text=bounded_text(r["FHSP"], 1024),
            fund_type=fund_type,
            income_label=label,
            nav_type=bounded_text(r.get("NAVTYPE"), 16),
            income_start_date=day(r["SDATE"]) if r.get("SDATE") else None,
            actual_income=optional_number(r.get("ACTUALSYI")),
            dividend_value=optional_number(r.get("FHFCZ")),
            dividend_per_ten=optional_number(r.get("FHFCZ10")),
            dividend_basis=bounded_text(r.get("FHFCBZ"), 64),
            distribution_type=bounded_text(r.get("DTYPE"), 64),
        )
        rows.append([stamp, *[values[k] for k in NAV_FIELDS]])
        previous = stamp
    return total, (fund_type, label, kind), rows


def finish_shares(rows, source, expected):
    result = sorted(rows)
    if len(result) != expected:
        raise ValueError("ETF完整份额集合数量不符")
    return validate_share(result, source)


def finish_nav(rows, first, last, expected):
    if len(rows) != expected or len({r[0] for r in rows}) != expected:
        raise ValueError("ETF净值跨页日期重复或集合不完整")
    rows = sorted(rows)
    if first[:4] == last[:4]:
        validate_nav(rows, first, last)
    return rows
