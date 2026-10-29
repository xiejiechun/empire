"""Explicit presentation contracts for each installed collection project."""

import json
from importlib.resources import files

from .preview_fields import (
    CITATION,
    EVENTS,
    HOLDERS,
    HOTLIST,
    ISSUE_DETAILS,
    LISTINGS,
    MARGIN,
    MEMBERS,
    PERFORMANCE,
    POOL,
    PRICE,
    REPURCHASE,
    RULES,
    SECURITY,
    columns,
)

FILTERS = {
    "code": ("证券代码", "text", "例如 000001，可输入代码前缀"),
    "security": ("证券代码", "text", "例如 000001.SZ"),
    "search": ("搜索", "search", "名称或代码"),
    "start": ("开始日期", "date", "不限"), "end": ("结束日期", "date", "不限"),
    "day": ("查询日期", "date", "YYYY-MM-DD"), "month": ("查询月份", "month", "YYYY-MM"),
    "industry": ("行业代码", "text", "从行业目录选择，或输入代码"),
    "selected_index": ("指数代码", "text", "从指数目录选择，或输入代码"),
    "theme_id": ("题材编号", "text", "从题材日目录选择"),
    "market": ("市场", "select", "全部市场"),
    "important": ("重要性", "select", "全部快讯"),
    "record_key": ("记录身份", "text", "从列表选择记录"),
    "plan_id": ("方案编号", "text", "从方案列表选择"),
}
TITLES = {
    "tdx-dividends": "分红方案与权益日期", "tdx-additional-issues": "增发方案与发行详情",
    "tdx-rights-issues": "配股方案与缴款安排", "tdx-suspensions": "停复牌事件日历",
    "tdx-listing-status": "暂停、恢复与终止上市", "tdx-company-renames": "公司名称沿革",
    "tdx-security-renames": "证券简称沿革", "tdx-st-implementation": "风险警示实施",
    "tdx-st-removal": "风险警示撤销", "tdx-unlocks": "限售解禁与持有人",
}


def presentation(task, view):
    renderer, title, description, definitions = _content(task, view)
    result = dict(renderer=renderer, title=title, description=description,
                  columns=columns(definitions), identity=_identity(task, view),
                  hidden=view.hidden, parent=view.parent,
                  notes=["空白表示来源未提供，不按零处理。无记录不代表该范围已采集完整。"],
                  filter_specs=[_filter(task, view, key) for key in view.filters])
    if task in ("ths-income", "ths-balance", "ths-cashflow"):
        result["statement_layouts"] = json.loads(files("empire.features.financial_statements")
            .joinpath("statement_layouts.json").read_text("utf8"))[task[4:]]
    if task == "tdx-additional-issues":
        result["detail_columns"] = columns(ISSUE_DETAILS)
    if task == "ths-holders":
        result["member_columns"] = columns(MEMBERS)
    if task == "ths-capital":
        from empire.features.ths_capital.contract import fields
        table = view.fixed["table"]
        result["columns"] = [dict(key=k, label=label, kind="decimal" if kind == "num" else
                                  "longtext" if kind == "text" else "date" if kind == "date" else "boolean" if kind == "bool" else "integer" if kind == "int" else "text")
                             for k, (label, kind) in fields(table).items() if k not in ("record_key", "section")]
        result["columns"].append(dict(key="in_window", label="属于当前来源窗口", kind="boolean"))
    if not view.hidden:
        _navigation(task, view, result)
    return result


def _filter(task, view, key):
    label, shape, placeholder = FILTERS[key]
    if key == "code" and task == "ths-index-prices":
        label, placeholder = "指数代码", "例如 000001"
    if key in ("start", "end"):
        basis = {
            "tdx-suspensions": "来源日历日", "ths-holders": "报告期", "tdx-unlocks": "解禁日",
            "tdx-unlock-industries": "解禁月份", "eastmoney-repurchases": "方案日期",
            "tdx-holder-count": "统计日期", "tdx-shareholder-changes": "变动结束日",
            "ths-listings": "上市日期", "ths-index-prices": "交易日期", "ths-yuanhang-prices": "交易日期",
            "sina-news": "发布日期", "tdx-hot-list": "上榜日期", "tdx-margin": "交易日期", "ths-capital": "公告日/报告期",
            "tdx-dividends": "事件日期（除权日优先）", "tdx-additional-issues": "事件日期（发行日优先）",
            "tdx-rights-issues": "除权日",
        }.get(task, "报告期" if task.startswith("tdx-earnings-") else "事件日期")
        if task == "ths-yuanhang-financial":
            basis = "除权日期" if view.id == "actions" else "股本生效日期"
        label = basis + ("从" if key == "start" else "至")
    item = dict(key=key, label=label, type=shape, placeholder=placeholder,
                required=view.hidden or key in ("security", "theme_id"))
    if key == "market":
        item["options"] = [dict(value=value, label=label) for value, label in
                           [("", "全部市场"), ("SH", "沪市"), ("SZ", "深市"), ("BJ", "北交所"), ("CN", "全国")]]
        if not task.startswith("rules-"):
            allowed = {"", "SH", "SZ"} if task == "tdx-suspensions" else {"", "SH", "SZ", "BJ"}
            item["options"] = [option for option in item["options"] if option["value"] in allowed]
    if key == "important":
        item["options"] = [dict(value="", label="全部快讯"), dict(value="true", label="仅重要快讯")]
    return item


def _navigation(task, view, result):
    target, mapping = "", {}
    if task == "tdx-hot-list":
        target, mapping = view.id + ":detail", dict(security="unified_code", day="list_date")
    elif task == "ths-holders":
        target, mapping = view.id + ":detail", dict(record_key="report_key")
    elif task == "ths-capital":
        target, mapping = view.id + ":detail", dict(record_key="record_key")
    elif task.startswith("rules-"):
        target, mapping = view.id + ":detail", dict(record_key="citation_key")
    elif task in ("ths-listings", "ths-income", "ths-balance", "ths-cashflow"):
        target, mapping = view.id + ":detail", dict(security="unified_code")
    elif task == "tdx-unlocks":
        target, mapping = view.id + ":detail", dict(record_key="group_key")
    elif task == "eastmoney-repurchases":
        target, mapping = view.id + ":detail", dict(plan_id="plan_id")
    elif task == "ths-industries" and view.id == "directory":
        target, mapping = "members", dict(industry="industry_code")
    elif task == "ths-indices" and view.id == "indices":
        target, mapping = "members", dict(selected_index="index_code")
    elif task.startswith("kaipanla-") and view.id == "daily":
        target, mapping = "details", dict(theme_id="theme_id")
    if target:
        result.update(detailView=target, detailFilters=mapping)


def _identity(task, view):
    if task == "tdx-industry-margin":
        return ["trade_date", "industry_name"]
    if task == "ths-holders":
        return ["report_key"]
    if task.removeprefix("tdx-").replace("-", "_") in PERFORMANCE:
        return ["record_key"]
    if task.startswith("rules-"):
        return ["citation_key" if view.hidden else "record_key"]
    if task == "ths-capital" or task in EVENTS:
        return ["record_key", "unified_code", "event_date", "suspended_at", "resumed_at",
                "old_name", "new_name", "source_note", "reason"]
    if task.startswith("kaipanla-"):
        return ["relation_id"] if view.id == "details" else ["theme_id"]
    if task in ("ths-income", "ths-balance", "ths-cashflow"):
        return ["unified_code", "report_date"]
    if task == "tdx-hot-list":
        return ["unified_code", "list_date"]
    if task == "eastmoney-repurchases":
        return ["plan_id"]
    if task == "tdx-unlock-industries":
        return ["unlock_month", "industry"]
    if task == "ths-industries":
        return ["industry_code", "unified_code"]
    if task == "ths-indices":
        return ["index_code", "source_code"]
    if task == "ths-index-prices":
        return ["index_code", "trade_date"]
    if task == "ths-yuanhang-financial":
        return ["ex_date", "event_key"] if view.id == "actions" else ["effective_date"]
    if task == "sina-news":
        return ["news_id"]
    if task == "cninfo-calendar":
        return ["trade_date"]
    if task in ("ths-stocks", "sina-stocks", "ths-listings"):
        return ["unified_code"]
    return ["unified_code", "trade_date"]


def _content(task, view):
    if task == "tdx-industry-margin":
        return "directory", "行业融资融券", "2016年起来源完整日期集合；搜索需填写完整行业名称。日期不是公布时间，来源未给历史分类版本。", "trade_date:统计日期:date|industry_name:行业名称|financing_balance:融资余额:decimal:亿元|financing_buy:融资买入额:decimal:亿元|financing_repay:融资偿还额:decimal:亿元|lending_balance:融券余额:decimal:万元|lending_volume:融券余量:decimal:万股|lending_sell:融券卖出量:decimal:万股|lending_repay:融券偿还量:decimal:万股|margin_difference:融资融券差值:decimal:亿元"
    if task == "tdx-margin":
        return "directory", "个股融资融券历史", "每股完整历史；偿还与占比按页面公式计算。最早记录以零前值计算并标记；交易日期不是公布时间。", MARGIN
    if task.startswith("rules-"):
        from empire.features.trading_rules.contract import KINDS
        title = KINDS[task[6:].replace("-", "_")]
        return "rules", title + (" · 官方依据" if view.hidden else ""), "按市场、条件和生效区间阅读规则；选择参数查看所据官方条款。", CITATION if view.hidden else RULES
    if task in ("ths-stocks", "sina-stocks"):
        return "directory", "当前统一证券名录", "两个来源共同更新同一份当前股票列表；这里展示正式统一列表，不代表仅由本任务采集。", SECURITY + "|market:市场|source:当前列表发布来源"
    if task == "sina-news":
        return "news", "财经快讯时间线", "按发布时间阅读新闻正文；筛选关键词或日期，保留来源修订。", "published_at:发布时间:date|title:标题|content:正文:longtext|is_important:重要快讯:boolean|tags:标签:tags|source_updated_at:来源更新时间:date|url:新闻链接:url|news_id:新闻编号"
    if task == "cninfo-calendar":
        return "calendar", "交易日历", "按月区分交易日、休市日和缺失日期；未来安排以来源当前返回为准。", "trade_date:日期:date|is_trade:是否交易:boolean|updated_at:最后实际变更时间:date"
    if task == "ths-industries":
        defs = "industry_code:行业代码|name:行业名称|member_count:成分数量:integer" if view.id == "directory" else SECURITY + "|industry_code:行业代码|industry_name:所属行业"
        return "directory", "行业目录" if view.id == "directory" else "行业成分证券", "从行业进入成分证券；当前分类关系不表示历史归属。", defs
    if task == "ths-indices":
        defs = "index_code:指数代码|index_name:指数名称|source_group:来源分组|members_available:来源提供成员:boolean|member_count:成员数:integer" if view.id == "indices" else "index_code:指数代码|index_name:指数名称|source_code:来源证券代码|unified_code:统一证券代码|name:证券名称|members_available:来源提供成员:boolean"
        return "directory", "指数目录" if view.id == "indices" else "指数成分证券", "从指数进入成分；来源暂无成员不能解释为零成员，当前目录不提供历史调样。", defs
    if task in ("ths-income", "ths-balance", "ths-cashflow"):
        name = {"ths-income": "利润表", "ths-balance": "资产负债表", "ths-cashflow": "现金流量表"}[task]
        basis = "期末时点" if task == "ths-balance" else "年初至报告期累计"
        return "statement", name + " · 报告期比较", f"同一证券按报告期比较完整科目；金额为人民币元，{basis}。来源没有公告日期，不能直接当作历史选股可用日。", SECURITY + "|report_date:报告期:date|currency:币种|period_basis:期间口径"
    if task == "ths-holders":
        return "holdings", view.title, "先选择报告，再查看当期与退出名单；来源比例、数量缺值及质量标记分别呈现。", HOLDERS
    if task == "ths-capital":
        return "capital", view.title, "按公司与来源栏目阅读资本运作；报告期、公告日和当前窗口分别保留，金额遵循行内币种。", ""
    if task == "tdx-hot-list":
        return "hotlist", "龙虎榜原因与交易席位", "选择上榜日期查看全部上榜原因和买卖席位；目录列示与明细可用性分开呈现。", HOTLIST
    if task == "ths-listings":
        return "events", "上市发行档案", "查看上市日期、发行定价与募资信息；选择证券阅读完整发行沿革。", SECURITY + "|" + LISTINGS + ("|history:发行沿革:longtext|detail_status:当前来源状态" if view.hidden else "|detail_status:当前来源状态")
    if task == "eastmoney-repurchases":
        detail = "|objective:回购目的:longtext|remark:方案说明:longtext|progress_remark:进度说明:longtext|start_date:开始日期:date|end_date:结束日期:date|plan_price_upper:计划价格上限:decimal:元|plan_price_lower:计划价格下限:decimal:元|actual_price_upper:实际价格上限:decimal:元|actual_price_lower:实际价格下限:decimal:元" if view.hidden else ""
        return "events", "回购计划与实际进展", "计划上限、下限和实际执行分开阅读；来源未知进度不推断为完成或取消。", SECURITY + "|" + REPURCHASE + detail
    kind = task.removeprefix("tdx-").replace("-", "_")
    if kind in PERFORMANCE:
        from empire.features.performance.contract import UNIT_KINDS
        return "events", UNIT_KINDS[kind][0], "日期筛选遵循本项目业务日期；公告/披露日期单独展示，保留来源原始口径和缺值。", SECURITY + "|" + PERFORMANCE[kind]
    if task == "tdx-unlock-industries":
        return "events", "行业月度解禁规模", "按解禁月份比较行业；市值与占比采用来源基准日，不视为历史当时价格。", "unlock_month:解禁月份:date|industry:行业|basis_date:估值基准日:date|shares:解禁数量:decimal:股|unlock_value:解禁市值:decimal:元|market_cap:总市值:decimal:元|negotiable_cap:流通市值:decimal:元|market_percent:占总市值比例:decimal:%|float_percent:占流通市值比例:decimal:%"
    if task in EVENTS:
        defs = SECURITY + "|" + EVENTS[task]
        if task == "tdx-unlocks" and view.hidden:
            defs = "unified_code:证券代码|unlock_date:解禁日期:date|holder:持有人|reason:解禁原因|shares:解禁股份:decimal:股|occurrence:来源出现次数:integer"
        note = "日期筛选为来源日历出现日期；逐条列出筛选范围内的实际出现日期，停复牌生效时间独立呈现。未知复牌日不作推断。" if task == "tdx-suspensions" else "按业务事件阅读日期、方案和变动前后信息；保留来源并列记录与未知值。"
        return "events", TITLES[task], note, defs
    if task.startswith("kaipanla-"):
        if view.id == "daily":
            return "themes", "题材热度日目录", "查看当日题材层级、热度与涨停数；选择题材阅读说明和关联证券。", "rank_no:来源排名:integer|name:题材名称|parent_id:父题材编号|hot_score:热度:decimal|change_rate:涨幅:decimal:%|limit_up_count:涨停数:integer|new_flag:新增标记:boolean"
        return "themes", "题材逻辑与关联证券", "题材介绍和证券入选原因分别阅读；同一证券可在不同分类出现。", "unified_code:证券代码|stock_name:证券名称|category_name:题材分类|reason:入选原因:longtext|first_shelved_at:首次收录时间:date|is_new:新增:boolean|is_hot:热门:boolean"
    if task == "ths-index-prices":
        return "prices", "指数日线", "选择单一指数比较价格；成交量、成交额保留来源单位，质量标记不被隐藏。", "index_code:指数代码|name:指数名称|" + PRICE.replace(":元", ":点") + "|volume:成交量（来源口径）:decimal|amount:成交额:decimal:元|price_relation_valid:价格关系有效:boolean|volume_amount_valid:量额有效:boolean"
    if task == "ths-yuanhang-prices":
        return "prices", "不复权日行情", "按证券浏览不复权OHLC与成交量额；图表仅概览当前页，完整值见明细。", PRICE + "|volume_shares:成交量:decimal:股|amount_yuan:成交额:decimal:元|quality_flags:质量标记:integer"
    if task == "ths-yuanhang-financial":
        defs = "ex_date:除权日期:date|cash_per_share:每股现金:decimal:元/股|bonus_ratio:送股比例:decimal:股/股|transfer_ratio:转增比例:decimal:股/股|rights_ratio:配股比例:decimal:股/股|rights_price:配股价格:decimal:元" if view.id == "actions" else "effective_date:生效日期:date|shares:股本:decimal:股"
        return "events", view.title, "权息事件与总、流通、自由流通股本分开呈现；同日多事件不自动合并。", defs
    if task == "ths-yuanhang-reason":
        return "reason", "证券涨跌停原因", "按证券和交易日阅读来源原因；来源未提供与未采集分别保留。", "trade_date:交易日期:date|unified_code:证券代码|name:证券名称|reason_kind:原因类型|availability:来源可用性|reason_text:原因正文:longtext"
    if task.startswith("ths-yuanhang-"):
        from empire.features.yuanhang_limits.contract import POOLS
        title = POOLS[task.removeprefix("ths-yuanhang-").replace("-", "_")]
        return "pool", title + (" · 盘中快照" if view.id == "live" else " · 日终成员"), "日终归档与Redis盘中快照分栏；没有快照不表示空池，多页采样不表示同一瞬间冻结。", POOL
    raise ValueError("未登记专用预览呈现：" + task)
