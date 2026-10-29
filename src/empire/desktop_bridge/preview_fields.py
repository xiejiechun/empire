"""Business vocabulary for preview columns; no raw-column inference in the UI."""


def columns(definitions):
    result = []
    for item in definitions.split("|"):
        parts = item.strip().split(":")
        if len(parts) < 2:
            continue
        key, label, *extra = parts
        result.append(dict(key=key, label=label, kind=extra[0] if extra else "text",
                           **({"unit": extra[1]} if len(extra) > 1 else {})))
    return result


SECURITY = "unified_code:证券代码|name:名称"
PRICE = "trade_date:交易日期:date|open:开盘:decimal:元|high:最高:decimal:元|low:最低:decimal:元|close:收盘:decimal:元"
PERFORMANCE = {
    "earnings_forecast": "report_date:报告期:date|announcement_date:公告日期:date|forecast_type:预告类型|forecast_text:预告内容:longtext",
    "earnings_quick": "report_date:报告期:date|announcement_date:公告日期:date|net_profit:净利润:decimal:元|eps:每股收益:decimal:元/股|roe:净资产收益率:decimal:%|assets:资产:decimal:元|equity:净资产:decimal:元|profit_basis:利润口径|profit_scope:利润范围|roe_scope:收益率口径|previous_profit:上期利润:decimal:元|profit_change:利润变动:decimal:%|previous_roe:上期净资产收益率:decimal:%|roe_change:收益率变动:decimal:%|comparison_value:来源比较值:decimal:元|source_date:来源日期:date|source_id:来源公司编号",
    "earnings_disclosure": "report_date:报告期:date|first_scheduled:首次预约:date|changed_1:第一次变更:date|changed_2:第二次变更:date|changed_3:第三次变更:date|actual_date:实际披露:date",
    "earnings_report": "report_date:报告期:date|announcement_date:公告日期:date|revenue:营业收入:decimal:元|previous_revenue:上期营业收入:decimal:元|net_profit:净利润:decimal:元|previous_profit:上期净利润:decimal:元|operating_cashflow:经营现金流:decimal:元|eps:每股收益:decimal:元/股|roe:净资产收益率:decimal:%|previous_roe:上期净资产收益率:decimal:%",
    "holder_count": "statistics_date:统计日期:date|holders:股东户数:integer:户|holder_change:户数增减:integer:户|holder_change_pct:户数变动比例:decimal:%|average_float:户均流通股:decimal:股/户|top_float_shares:前十大流通股:decimal:股|top_float_pct:前十大流通占比:decimal:%|top_shares:前十大持股:decimal:股|top_pct:前十大占比:decimal:%",
    "shareholder_changes": "change_start:变动开始日期|change_end:变动结束日期:date|announcement_date:公告日期:date|actor:变动主体|shares_changed:变动股份:decimal:股|shares_after:变动后持股:decimal:股|price:成交均价:decimal:元/股|reason:变动原因:longtext|leader:关联高管|position:职务|relationship:关联关系|data_month:数据月份:date|occurrence:相同来源事实序号:integer",
}
EVENTS = {
    "tdx-dividends": "report_date:报告期:date|status:方案进度|cash_per_share:每股现金红利:decimal:元/股|bonus_per_share:每股送股:decimal:股/股|transfer_per_share:每股转增:decimal:股/股|record_date:股权登记日:date|ex_date:除权除息日:date|announcement_date:公告日期:date|tax_basis:税收口径|total_bonus_per_share:每股送转合计:decimal:股/股|earnings_per_share:每股收益:decimal:元/股|net_assets_per_share:每股净资产:decimal:元/股|capital_reserve_per_share:每股资本公积:decimal:元/股|retained_profit_per_share:每股未分配利润:decimal:元/股",
    "tdx-additional-issues": "issue_method:发行方式|issue_date:发行日期:date|listing_date:上市日期:date|issued_shares:发行数量:decimal:股|issue_price:发行价格:decimal:元|shares_before:发行前股本:decimal:股|shares_after:发行后股本:decimal:股|lock_months:限售月数:decimal:月|record_date:股权登记日:date|subscription_code:申购代码|public_issue_date:公开发行日期:date|private_issue_date:定向发行日期:date|status:来源进度",
    "tdx-rights-issues": "record_date:股权登记日:date|ex_date:除权基准日:date|payment_start:缴款开始日:date|payment_end:缴款截止日:date|rights_per_share:每股配股:decimal:股/股|rights_price:配股价格:decimal:元|issued_shares:发行数量:decimal:股|listing_date:上市日期:date|shares_before:配股前股本:decimal:股|shares_after:配股后股本:decimal:股|subscription_code:认购代码|status:来源进度",
    "tdx-suspensions": "source_dates:来源出现日（筛选范围内）:dates|suspended_at:停牌生效时间:date|resumed_at:复牌生效时间:date|suspension_type:停牌类型|source_note:来源说明:longtext|reason:停复牌原因:longtext",
    "tdx-listing-status": "event_date:生效日期:date|event_type:上市状态|description:来源说明:longtext",
    "tdx-company-renames": "event_date:变更日期:date|old_name:原公司名称|new_name:新公司名称|csrc_industry:证监会行业|tdx_industry:通达信行业|source_occurrences:来源出现次数:integer",
    "tdx-security-renames": "event_date:变更日期:date|old_name:原证券简称|new_name:新证券简称|csrc_industry:证监会行业|tdx_industry:通达信行业",
    "tdx-st-implementation": "event_date:实施日期:date|old_name:实施前简称|new_name:实施后简称|reason:风险警示原因:longtext",
    "tdx-st-removal": "event_date:撤销日期:date|old_name:撤销前简称|new_name:撤销后简称|reason:撤销原因:longtext",
    "tdx-unlocks": "unlock_date:解禁日期:date|industry:所属行业|reason:解禁类型|shares:解禁股份:decimal:股|total_shares:来源总股数:decimal:股|detail_status:股东明细状态|detail_count:股东明细条数:integer|reason_code:来源原因代码|occurrence:来源出现序号:integer",
}
HOLDERS = "unified_code:证券代码|instrument_name:证券或债券名称|report_date:报告期:date|report_type:报告类型|member_count:当期持有人:integer|exit_count:退出持有人:integer|total_quantity:来源持有数量合计:decimal|total_ratio:来源持有比例合计:decimal:%|ratio_basis:比例口径|quality_flags:来源质量标记:integer"
MEMBERS = "member_group:名单归属|source_rank:来源排名:integer|holder_name:持有人|quantity:持有数量:decimal|ratio:持有比例:decimal:%|change_quantity:变动数量:decimal|change_label:变动说明|actual_change:实际变动|share_type:股份类型|pledge_ratio:质押比例:decimal:%|pledge_status:质押状态"
HOTLIST = "unified_code:证券代码|list_date:上榜日期:date|directory_listed:目录列示:boolean|detail_status:详情状态|reason_count:上榜原因数:integer|seat_count:席位数:integer"
RULES = "market:市场|board:板块|condition_key:适用条件|parameter_key:规则参数|number_value:参数值:decimal|text_value:规则说明:longtext|unit:单位|effective_start:生效开始:date|effective_end:生效结束:date|start_time:时段开始|end_time:时段结束"
CITATION = "issuer:发布机构|title:规则文件|published_date:发布日期:date|clause_key:条款编号|excerpt:条款原文:longtext|source_url:官方来源:url"
POOL = "trade_date:交易日期:date|unified_code:证券代码|name:名称|latest:最新价:decimal:元|change_rate:涨跌幅:decimal:%|high_days:连板情况|reason_type:原因类型|top_concept:主要题材|rise_rate:涨速（来源口径）:decimal|order_volume:封单量（来源口径）:decimal|limit_up_suc_rate:涨停成功率:decimal:比例|limit_up_type:涨停类型|limit_down_type:跌停类型|high_days_value:来源板数指标:integer|is_new:新股标记:integer|is_again_limit:回封标记:integer|change_tag:异动标签|first_limit_up_time:首次涨停时间:time|last_limit_up_time:最后涨停时间:time|first_limit_down_time:首次跌停时间:time|last_limit_down_time:最后跌停时间:time|open_num:开板次数:integer|turnover:成交额:decimal:元|turnover_rate:换手率:decimal:%|order_amount:封单金额:decimal:元|currency_value:流通市值:decimal:元|sum_market_value:总市值:decimal:元"
REPURCHASE = "plan_date:方案日期:date|progress_code:回购进度|actual_through:实际进展截止日:date|plan_quantity_lower:计划数量下限:decimal:股|plan_quantity_upper:计划数量上限:decimal:股|plan_amount_lower:计划金额下限:decimal:元|plan_amount_upper:计划金额上限:decimal:元|actual_quantity:已回购数量:decimal:股|actual_amount:已回购金额:decimal:元|notice_date:公告日期:date|finish_date:完成日期:date|share_type:股份类型|updated_date:来源更新日:date|plan_updated_date:方案更新日:date|shareholder_notice_date:股东决议公告日:date|advance_date:提前完成日期:date"
LISTINGS = "listing_date:上市日期:date|establish_date:成立日期:date|issuance_num:发行股数:decimal:股|issuance_price:发行价格:decimal:元|first_day_open_price:上市首日开盘价:decimal:元|estimated_raised:预计募资:decimal:元|actual_raised:实际募资:decimal:元|issuance_pe:发行市盈率:decimal:倍|winning_rate:中签率:decimal:%|lead_underwriter:主承销商|sponsor:保荐机构"

ISSUE_DETAILS = "subscription_name:认购简称|lead_underwriter:主承销商|underwriting_method:承销方式|issue_targets:发行对象:longtext|pricing_method:定价方式:longtext|online_shares:网上发行数量:decimal:股|offline_shares:网下发行数量:decimal:股|gross_proceeds:募集资金总额:decimal:元|online_winning_percent:网上中签率:decimal:%|post_issue_eps:发行后每股收益:decimal:元/股|post_issue_net_assets:发行后每股净资产:decimal:元/股|first_day_open:首日开盘价:decimal:元|first_day_close:首日收盘价:decimal:元|first_day_open_change_percent:首日开盘涨幅:decimal:%|first_day_close_change_percent:首日收盘涨幅:decimal:%|online_allotment_date:网上配售日期:date|winning_announcement_date:中签公告日期:date"
