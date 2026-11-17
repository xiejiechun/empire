"""Read the one complete SZSE report in bounded memory, with exact share units."""

import io
import re
import zipfile
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from empire.features.etf_fundamentals.contract import bounded_text, day, number, validate_share

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xml(archive, name):
    data = archive.read(name)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("ETF工作簿不允许XML实体")
    return ET.fromstring(data)


def szse_workbook(raw, stamp, total, first_page):
    day(stamp)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("ETF份额工作簿超过4MiB")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 32
            or len({e.filename for e in entries}) != len(entries)
            or sum(e.file_size for e in entries) > 8 * 1024 * 1024
        ):
            raise ValueError("ETF工作簿成员/解压字节超限")
        if any(e.flag_bits & 1 or e.file_size > 4 * 1024 * 1024 for e in entries):
            raise ValueError("ETF工作簿加密或成员过大")
        sheets = xml(archive, "xl/workbook.xml").findall("m:sheets/m:sheet", NS)
        if len(sheets) != 1:
            raise ValueError("ETF工作簿不止一个数据集合")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = [
                "".join(t.text or "" for t in si.findall(".//m:t", NS))
                for si in xml(archive, "xl/sharedStrings.xml").findall("m:si", NS)
            ]
        records = xml(archive, "xl/worksheets/sheet1.xml").findall("m:sheetData/m:row", NS)
        if not records or len(records) != total + 1 or total > 5000:
            raise ValueError("ETF完整导出数量与报告总数不符")
        rows = []
        for record in records:
            values = {}
            for c in record.findall("m:c", NS):
                column = re.sub("[0-9]", "", c.get("r", ""))
                if (
                    column not in ("A", "B", "C", "D")
                    or column in values
                    or c.find("m:f", NS) is not None
                ):
                    raise ValueError("ETF工作簿列结构或公式无效")
                v = c.find("m:v", NS)
                value = (
                    v.text
                    if v is not None
                    else "".join(t.text or "" for t in c.findall(".//m:t", NS))
                )
                if c.get("t") == "s":
                    if not value or not value.isdecimal() or not 0 <= int(value) < len(shared):
                        raise ValueError("ETF工作簿共享字符串索引错误")
                    value = shared[int(value)]
                values[column] = value
            if set(values) != {"A", "B", "C", "D"}:
                raise ValueError("ETF工作簿缺必需列")
            rows.append([values[k] for k in ("A", "B", "C", "D")])
        if rows.pop(0) != ["日期", "基金代码", "基金简称", "基金规模(份)"]:
            raise ValueError("ETF导出字段或单位改变，拒绝猜测")
        facts = []
        for stamp_value, code, name, shares in rows:
            code = code.strip()
            if stamp_value != stamp or not re.fullmatch("[0-9]{6}", code):
                raise ValueError("ETF导出日期或代码不符")
            amount = number(shares.replace(",", ""))
            facts.append(
                [code + ".SZ", bounded_text(name, 128, required=True), amount, "etf", None]
            )
        facts.sort()
        validate_share(facts, "szse")
        values = {r[0]: Decimal(r[2]) for r in facts}
        for code, rounded in first_page.items():
            display = values.get(code, Decimal(-1)) / 10000
            # Historical JSON reports truncate two decimals; newer reports round.
            # Both are display checks only. SQL retains the exact XLSX shares.
            accepted = {
                display.quantize(Decimal(".01"), rounding=mode)
                for mode in (ROUND_DOWN, ROUND_HALF_UP)
            }
            if code not in values or Decimal(rounded) not in accepted:
                raise ValueError(
                    f"ETF导出与JSON首页身份/显示数值不符：{stamp} {code} "
                    f"导出份额={values.get(code)} 网页万份={rounded}，保留待重核"
                )
        return facts
