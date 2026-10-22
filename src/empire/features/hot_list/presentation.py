"""Source-aware HTML rendering and paired cross-direction totals."""

import html
from decimal import Decimal

STATUS = {
    "pending": "待补采",
    "present": "明细可用",
    "partial": "来源部分缺失",
    "source_empty": "来源无席位明细",
}


def shown(value):
    return "来源未提供" if value is None else html.escape(str(value))


def summary(data, reason):
    # Pair identical cross-direction disclosures, preserving same-side multiplicity.
    from collections import Counter

    seen, bought, sold = Counter(), Decimal(0), Decimal(0)
    for row in data["seats"]:
        if row["reason_code"] != reason:
            continue
        key = (row["seat_name"], row["buy_amount"], row["sell_amount"], row["reason_code"])
        opposite = (key, "S" if row["side"] == "B" else "B")
        if seen[opposite]:
            seen[opposite] -= 1
            continue
        seen[(key, row["side"])] += 1
        bought += Decimal(row["buy_amount"] or "0")
        sold += Decimal(row["sell_amount"] or "0")
    return bought, sold


def render(data):
    if not data:
        return "<p>尚无已归档数据。</p>"
    out = [
        "<h3>" + shown(data["unified_code"]) + " · " + data["list_date"] + "</h3>",
        "<p>" + STATUS[data["detail_status"]] + "；金额单位：万元；成交量保留来源“万”单位。</p>",
    ]
    if data["detail_status"] == "source_empty" and data["seats"]:
        out.append("<p><b>本次来源缺席位，以下保留上次有效历史参考，不代表本次来源完整。</b></p>")
    for reason in data["reasons"]:
        out.append(
            "<h4>" + shown(reason["reason_code"]) + " · " + shown(reason["reason"]) + "</h4>"
        )
        out.append(
            "<p>成交额："
            + shown(reason["turnover"])
            + "；成交量："
            + shown(reason["volume"])
            + "；收盘价："
            + shown(reason["close_price"])
            + "元；涨跌幅："
            + shown(reason["change_pct"])
            + "%</p>"
        )
        out.append(
            '<table border="1" cellspacing="0" cellpadding="4"><tr><th>方向/排名</th><th>席位</th><th>买入万元</th><th>买入占比%</th><th>卖出万元</th><th>卖出占比%</th><th>净额万元</th><th>来源标签</th></tr>'
        )
        for seat in data["seats"]:
            if seat["reason_code"] != reason["reason_code"]:
                continue

            def ratio(key):
                return (
                    None
                    if seat[key] is None or reason["turnover"] in (None, "0")
                    else format(Decimal(seat[key]) / Decimal(reason["turnover"]) * 100, ".4f")
                )

            labels = [
                seat["extension"][k] for k in ("bq1", "bq2", "bq3", "bq4") if seat["extension"][k]
            ]
            labels.extend(
                r[6] + "（" + r[0] + "）"
                for r in data["auxiliary"]["related"]
                if r[2] == seat["reason_code"] and r[3] == seat["seat_name"]
            )
            values = [
                ("买" if seat["side"] == "B" else "卖") + str(seat["seat_rank"]),
                seat["seat_name"],
                seat["buy_amount"],
                ratio("buy_amount"),
                seat["sell_amount"],
                ratio("sell_amount"),
                seat["net_amount"],
                "、".join(labels),
            ]
            out.append("<tr>" + "".join("<td>" + shown(v) + "</td>" for v in values) + "</tr>")
        out.append("</table>")
        if not any(r["reason_code"] == reason["reason_code"] for r in data["seats"]):
            out.append("<p>来源未提供席位，披露金额合计未知。</p>")
            continue
        bought, sold = summary(data, reason["reason_code"])
        out.append(
            f"<p>席位披露金额合计：买入{bought}万元；卖出{sold}万元；净额{bought - sold}万元。缺失方向金额未贡献数值，不能当作已披露零值。</p>"
        )
    out.append(
        "<h4>附带活动信息（查询时刻口径）</h4><p>近三个月次数不代表历史当天已知值；营业部名称也可能按来源当前名称展示。</p>"
    )
    out.extend(
        "<p>" + shown(name) + "：" + str(count) + "次</p>"
        for name, count in data["auxiliary"]["counts"]
    )
    out.append(
        "<p>机构辅助次数："
        + shown(data["auxiliary"]["institution_count"])
        + "；本次存储版本观测："
        + shown(data["version_observed_at"])
        + "（北京时间）。</p>"
    )
    return "".join(out)
