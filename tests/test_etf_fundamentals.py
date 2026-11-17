import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest

from empire.features.etf_fundamentals.contract import (
    NAV_FIELDS,
    coverage_through,
    validate_nav,
    validate_share,
)
from empire.features.etf_fundamentals.source import (
    SQL_IDS,
    finish_nav,
    nav_page,
    sse_page,
)
from empire.features.etf_fundamentals.xlsx import szse_workbook


def nav_response(page=1, total=1, records=None, fund_type="001", label=None):
    row = dict(
        FSRQ="2026-11-13",
        DWJZ="1.2345",
        LJJZ="2.3456",
        JZZZL="-0.10",
        SGZT="暂停申购",
        SHZT="开放赎回",
        FHSP="每份派现金0.01元",
        NAVTYPE="1",
        SDATE="",
    )
    return dict(
        ErrCode=0,
        Data=dict(LSJZList=[row] if records is None else records, FundType=fund_type, SYType=label),
        PageIndex=page,
        PageSize=20,
        TotalCount=total,
    )


def parsed_nav(**kw):
    d = nav_response(**kw)
    return nav_page(json.dumps(d).encode(), "510300.SH", "2026-01-01", "2026-11-16", d["PageIndex"])


def sse_response(rows=None):
    records = (
        [
            dict(
                STAT_DATE="2026-11-13",
                SEC_CODE="510300",
                SEC_NAME="沪深300ETF",
                TOT_VOL="123.456789",
                ETF_TYPE="单市",
            )
        ]
        if rows is None
        else rows
    )
    return dict(
        sqlId=SQL_IDS["etf"],
        result=records,
        pageHelp=dict(total=len(records), pageSize=1000, pageNo=1, pageCount=int(bool(records))),
    )


def workbook(rows, header=None):
    header = header or ["日期", "基金代码", "基金简称", "基金规模(份)"]
    records = [header, *rows]
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    for index, row in enumerate(records, 1):
        xml += '<row r="' + str(index) + '">'
        for col, value in zip("ABCD", row, strict=True):
            xml += (
                '<c r="'
                + col
                + str(index)
                + '" t="inlineStr"><is><t>'
                + escape(value)
                + "</t></is></c>"
            )
        xml += "</row>"
    xml += "</sheetData></worksheet>"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", xml)
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="ETF"/></sheets></workbook>',
        )
    return output.getvalue()


def test_exact_exchange_units_and_empty_semantics():
    d = sse_response()
    total, pages, rows = sse_page(json.dumps(d).encode(), "2026-11-13", "etf", 1)
    assert (total, pages, rows[0][2]) == (1, 1, "1234567.89")
    assert sse_page(json.dumps(sse_response([])).encode(), "2005-02-23", "etf", 1) == (0, 0, [])
    for mutate in (
        lambda q: q["pageHelp"].update(total=2),
        lambda q: q["result"][0].update(STAT_DATE="2026-11-12"),
    ):
        d = sse_response()
        mutate(d)
        with pytest.raises(ValueError):
            sse_page(json.dumps(d).encode(), "2026-11-13", "etf", 1)


def test_szse_exact_export_is_not_rounded_json_times_ten_thousand():
    raw = workbook([["2026-11-13", "159001  ", "货币ETF", "4855333.00"]])
    rows = szse_workbook(raw, "2026-11-13", 1, {"159001.SZ": "485.53"})
    assert rows[0][2] == "4855333"
    for total, first in (
        (2, {"159001.SZ": "485.53"}),
        (1, {"159002.SZ": "485.53"}),
        (1, {"159001.SZ": "485.54"}),
    ):
        with pytest.raises(ValueError):
            szse_workbook(raw, "2026-11-13", total, first)
    with pytest.raises(ValueError, match="单位"):
        szse_workbook(
            workbook([], header=["日期", "基金代码", "基金简称", "基金规模(万份)"]),
            "2026-11-13",
            0,
            {},
        )


def test_szse_historical_truncated_display_retains_exact_shares():
    raw = workbook([["2016-12-21", "159001", "货币ETF", "5208781"]])
    assert szse_workbook(raw, "2016-12-21", 1, {"159001.SZ": "520.87"})[0][2] == "5208781"
    assert szse_workbook(raw, "2016-12-21", 1, {"159001.SZ": "520.88"})[0][2] == "5208781"
    with pytest.raises(ValueError):
        szse_workbook(raw, "2016-12-21", 1, {"159001.SZ": "520.86"})


def test_nav_seven_columns_nulls_income_and_unknown_basis():
    _, _, rows = parsed_nav()
    r = dict(zip(NAV_FIELDS, rows[0][1:], strict=True))
    assert (
        r["unit_nav"],
        r["purchase_status"],
        r["redemption_status"],
        r["distribution_text"],
    ) == ("1.2345", "暂停申购", "开放赎回", "每份派现金0.01元")
    assert r["currency"] is None
    _, _, rows = parsed_nav(fund_type="005", label="每百份收益")
    r = dict(zip(NAV_FIELDS, rows[0][1:], strict=True))
    assert (
        r["unit_nav"] is None and r["income_value"] == "1.2345" and r["income_basis_shares"] is None
    )
    validate_nav(rows, "2026-01-01", "2026-11-16")
    d = nav_response()
    d["Data"]["LSJZList"][0]["DWJZ"] = ""
    _, _, rows = nav_page(json.dumps(d).encode(), "510300.SH", "2026-01-01", "2026-11-16", 1)
    assert rows[0][2] is None


@pytest.mark.parametrize("mode", ["null", "columns", "tail", "duplicate", "overflow"])
def test_deceptive_empty_missing_columns_and_bad_page_rejected(mode):
    d = nav_response()
    if mode == "null":
        d["Data"] = None
    elif mode == "columns":
        del d["Data"]["LSJZList"][0]["SGZT"]
    elif mode == "tail":
        d["TotalCount"] = 2
    elif mode == "duplicate":
        d["Data"]["LSJZList"] *= 2
        d["TotalCount"] = 2
    else:
        d["Data"]["LSJZList"][0]["DWJZ"] = "1.00000000001"
    with pytest.raises(ValueError):
        nav_page(json.dumps(d).encode(), "510300.SH", "2026-01-01", "2026-11-16", 1)


def test_same_count_other_identity_and_cross_page_duplicates_rejected():
    rows = [["510300.SH", "ETF", "1", "etf", None]]
    with pytest.raises(ValueError):
        validate_share(rows * 2, "sse")
    with pytest.raises(ValueError):
        validate_share(rows, "szse")
    values = parsed_nav()[2]
    with pytest.raises(ValueError):
        finish_nav(values * 2, "2026-01-01", "2026-11-16", 2)


def test_first_partial_year_and_cross_year_coverage():
    observed = "2026-11-17T00:00:00.000000+00:00"
    assert coverage_through([["2004-12-30", "2004-12-31", observed]], 2004) == "2004-12-31"
    assert coverage_through([["2026-11-01", "2026-11-16", observed]], 2026) is None


def test_zero_income_basis_rejected_before_sql_check():
    rows = parsed_nav(fund_type="005", label="每百份收益")[2]
    rows[0][NAV_FIELDS.index("income_basis_shares") + 1] = "0"
    with pytest.raises(ValueError, match="大于0"):
        validate_nav(rows, "2026-01-01", "2026-11-16")
