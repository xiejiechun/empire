"""Task-owned preview declarations: only existing formal read services are exposed."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class View:
    id: str
    title: str
    capability: str
    method: str
    mode: str = "cursor"
    fixed: dict = field(default_factory=dict)
    filters: tuple = ("code", "start", "end")


def views(task):
    simple = {
        "ths-listings": ("listings.query", "list_records"),
        "tdx-listing-status": ("listing_status.query", "list_events"),
        "tdx-unlocks": ("unlocks.tdx_query", "list_records"),
        "tdx-unlock-industries": ("unlock_industries.tdx_query", "list_records"),
        "eastmoney-repurchases": ("repurchases.query", "list_plans"),
        **{
            f"tdx-{k.replace('_', '-')}": (f"{k}.tdx_query", "list_records")
            for k in (
                "earnings_forecast",
                "earnings_quick",
                "earnings_disclosure",
                "earnings_report",
                "holder_count",
                "shareholder_changes",
            )
        },
        "tdx-company-renames": ("names.company.query", "list_events"),
        "tdx-security-renames": ("names.security.query", "list_events"),
        "tdx-st-implementation": ("st.implementation.query", "list_events"),
        "tdx-st-removal": ("st.removal.query", "list_events"),
        "ths-index-prices": ("index.prices.query", "browse"),
    }
    if task in simple:
        cap, method = simple[task]
        return [
            View(
                "records",
                "已归档数据",
                cap,
                method,
                filters=("industry", "start", "end")
                if task == "tdx-unlock-industries"
                else ("code", "start", "end"),
            )
        ]
    if task.startswith("rules-"):
        return [
            View(
                "rules",
                "规则数据",
                "rules." + task[6:].replace("-", "_") + ".query",
                "list_rules",
                filters=("market",),
            )
        ]
    if task in ("ths-stocks", "sina-stocks"):
        return [
            View(
                "stocks",
                "当前统一股票列表",
                "stocks.query",
                "list_stocks",
                "offset",
                filters=("search",),
            )
        ]
    if task == "sina-news":
        return [
            View(
                "news",
                "财经快讯",
                "news.query",
                "list_news",
                "news",
                filters=("search", "start", "end"),
            )
        ]
    if task == "cninfo-calendar":
        return [
            View("calendar", "交易日历", "calendar.query", "month", "month", filters=("month",))
        ]
    if task == "ths-industries":
        return [
            View(
                "members",
                "行业与成分",
                "industries.query",
                "list_members",
                "offset",
                filters=("search",),
            )
        ]
    if task == "ths-indices":
        return [
            View(mode, title, "indices.query", "browse", fixed={"mode": mode}, filters=("search",))
            for mode, title in [("indices", "指数目录"), ("members", "指数成分")]
        ]
    if task == "ths-holders":
        return [
            View(k, title, k + ".query", "browse")
            for k, title in [
                ("top_holders", "前十大股东"),
                ("float_holders", "前十大流通股东"),
                ("bond_holders", "债券持有人"),
            ]
        ]
    if task == "ths-capital":
        from empire.features.ths_capital.contract import SECTIONS, TABLE_SECTIONS

        return [
            View(
                table + ":" + section,
                SECTIONS[section]
                + " · "
                + {
                    "capital_funding": "资金",
                    "capital_project": "项目",
                    "capital_transaction": "交易",
                    "capital_equity_summary": "汇总",
                    "capital_equity_position": "持仓",
                    "capital_ipo": "参股",
                    "capital_encumbrance": "原事件",
                    "capital_release": "解除记录",
                }[table],
                "ths_capital.query",
                "browse",
                fixed=dict(table=table, section=section),
            )
            for table, sections in TABLE_SECTIONS.items()
            for section in sections
        ]
    for kind in ("income", "balance", "cashflow"):
        if task == "ths-" + kind:
            return [
                View(
                    kind,
                    "报告期数据",
                    kind + ".query",
                    "list_statements",
                    "list",
                    filters=("code",),
                )
            ]
    if task == "tdx-suspensions":
        return [View("events", "停复牌事件", "suspensions.query", "list_events", "offset")]
    for kind in ("dividends", "additional_issues", "rights_issues"):
        if task == "tdx-" + kind.replace("_", "-"):
            return [View(kind, "事件与方案", kind + ".query", "list_events", "list")]
    if task in ("kaipanla-themes", "kaipanla-theme-details"):
        return [
            View("daily", "题材日目录", "themes.query", "daily", "day", filters=("day",)),
            View(
                "details",
                "题材详情与关联证券",
                "themes.query",
                "detail_page",
                "theme",
                filters=("theme_id",),
            ),
        ]
    if task == "ths-yuanhang-prices":
        return [
            View(
                "prices",
                "不复权日行情",
                "yuanhang.history.query",
                "prices",
                "security",
                filters=("security", "start", "end"),
            )
        ]
    if task == "ths-yuanhang-financial":
        return [
            View(
                "actions",
                "权息事件",
                "yuanhang.history.query",
                "actions",
                "security",
                filters=("security", "start", "end"),
            ),
            *[
                View(
                    k,
                    t,
                    "yuanhang.history.query",
                    "capital_points",
                    "security",
                    fixed={"kind": k},
                    filters=("security", "start", "end"),
                )
                for k, t in [
                    ("total", "总股本"),
                    ("circulating", "流通股本"),
                    ("free_float", "自由流通股本"),
                ]
            ],
        ]
    if task.startswith("ths-yuanhang-"):
        pool = task.removeprefix("ths-yuanhang-").replace("-", "_")
        if pool == "reason":
            return [
                View(
                    "reason",
                    "涨停原因",
                    "yuanhang.limits.query",
                    "reason",
                    "reason",
                    filters=("security", "day"),
                )
            ]
        return [
            View(
                "daily",
                "日终池",
                "yuanhang.limits.query",
                "members",
                "pool",
                fixed={"pool": pool},
                filters=("day",),
            ),
            View(
                "live",
                "盘中快照",
                "yuanhang.limits.query",
                "browse",
                "live",
                fixed={"pool": pool},
                filters=("day",),
            ),
        ]
    return []
