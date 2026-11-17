# 已接入数据与实际存量盘点（2026-11-02）

## 核查范围与口径

核查开始：2026-11-02T19:39:17.478732+08:00；主体查询结束：2026-11-02T19:39:40.915205+08:00，均为北京时间。项目根目录与当前桌面启动器配置指向同一 MySQL 目标，未输出连接凭据。

以正式采集规则登记的 52 项任务及其 65 张去重业务/明细/覆盖证明表为范围。SQL 主体在只读一致性快照中逐表 COUNT(*)、可用时 COUNT(DISTINCT unified_code) 及业务日期 MIN/MAX；单条查询上限 8 秒。未启动采集或归档、未请求来源、未改配置或业务数据。

远航日线组合聚合超过 8 秒预算，随后改为单独只读 COUNT(*)，在 15 秒上限内得到 17,033,204 行；该计数是稍后独立读取，不与主体共用原子快照，本次未取得该事实表的证券数和日期两端。年度证明数量不能替代日线事实的精确覆盖。

这是存量调查，不是重新执行来源完整性验收。未验证逐证券缺日、分页集合、来源内容一致性、全部待归档清队或 Redis 盘中快照；不宣称全市场全历史完成。没有把内部状态表、设置表、历史退役表和静态维护映射算作采集事实。

## 主要发现

- 当前股票目录 5,579 只；历史事件和明细可能涉及目录之外证券，不能用当前目录数作为所有表的覆盖率分母。
- 利润表 336,933 行，资产负债表 325,241 行，现金流量表 326,289 行，均涉及 5,584 只历史证券，报告期上界为 2026-09-30。
- 个股融资融券明细 6,293,546 行，涉及 4,077 只证券；5,579 条证券覆盖证明不表示每只证券都有非空融资融券记录。
- 龙虎榜证券日 209,289 条，原因 270,496 条，席位 2,337,369 条，属于不同粒度，不能相加当成上榜次数。
- 行业 90 个；指数 573 个；题材最新详情 251 份。成员关系数不是独立证券数，也不证明历史成员可重建。
- 市场两融四个序列共 12,982 行，最新日期 2026-10-30；行业两融事实最新日期 2026-10-29。最新日早于今天不直接判定程序漏采，需核实来源更新。
- 资本交易事件最小日期为 0226-09-23，属于明显异常日期，根因本次未调查；不得解释为覆盖公元 226 年。未来计划、未来报告期与异常日期分别处理，均不提前作为已发生事实。

## 当前每项任务对应的数据

任务名称以专项主题加任务 ID 精确定位。共表任务不能仅凭表非空证明该任务自己的子类已齐；下方存量表是表级统计，未另做子类覆盖验收。七项交易规则共用条款及参数表，五池共用池头与成员表，股票两来源共用当前目录。

| 任务 ID | 数据主题 | 来源 | 正式表组 |
| --- | --- | --- | --- |
| `sina-stocks` | 股票列表 | sina | `stock` |
| `ths-stocks` | 股票列表 | ths | `stock` |
| `sina-news` | 财经快讯 | sina | `finance_news` |
| `cninfo-calendar` | 交易日历 | cninfo | `trade_calendar` |
| `tdx-suspensions` | 历史停复牌 | tdx | `suspension_event`, `suspension_source_date` |
| `tdx-listing-status` | 暂停恢复终止上市 | tdx | `security_listing_event` |
| `tdx-company-renames` | 公司与股票更名 | tdx | `security_name_change` |
| `tdx-security-renames` | 公司与股票更名 | tdx | `security_name_change` |
| `tdx-st-implementation` | 实施ST与撤销ST | tdx | `security_st_event` |
| `tdx-st-removal` | 实施ST与撤销ST | tdx | `security_st_event` |
| `tdx-earnings-forecast` | 通达信业绩预告 | tdx | `earnings_forecast` |
| `tdx-earnings-quick` | 通达信业绩快报 | tdx | `earnings_quick` |
| `tdx-earnings-disclosure` | 通达信业绩披露时间 | tdx | `earnings_disclosure` |
| `tdx-earnings-report` | 通达信业绩报告 | tdx | `earnings_report` |
| `tdx-holder-count` | 通达信股东户数 | tdx | `shareholder_count` |
| `tdx-shareholder-changes` | 通达信重要股东持股变动 | tdx | `shareholder_change` |
| `ths-income` | 同花顺三大报表 | ths | `income_statement` |
| `ths-balance` | 同花顺三大报表 | ths | `balance_statement` |
| `ths-cashflow` | 同花顺三大报表 | ths | `cashflow_statement` |
| `ths-holders` | 同花顺前十大持有人 | ths | `holder_report`, `holder_member` |
| `ths-listings` | 上市与发行资料 | ths | `stock_listing` |
| `ths-industries` | 同花顺当前行业 | ths | `industry`, `industry_member` |
| `ths-indices` | 同花顺当前指数及成分 | ths | `stock_index`, `stock_index_member` |
| `ths-index-prices` | 同花顺指数历史日行情 | ths | `index_daily_price`, `index_price_year` |
| `eastmoney-repurchases` | 股票回购 | eastmoney | `stock_repurchase_plan` |
| `tdx-dividends` | 分红送转 | tdx | `dividend_plan` |
| `tdx-additional-issues` | 增发 | tdx | `additional_issue` |
| `tdx-rights-issues` | 配股 | tdx | `rights_issue` |
| `rules-limit-rules` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-settlement-rules` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-lot-rules` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-tick-rules` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-sessions` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-stamp-duty` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `rules-transfer-fee` | 交易规则与税费 | reviewed_rules | `trading_rule_citation`, `trading_rule_value` |
| `tdx-unlocks` | 大小非解禁个股与明细 | tdx | `restricted_share_unlock`, `restricted_share_unlock_detail` |
| `tdx-unlock-industries` | 大小非解禁行业 | tdx | `restricted_share_unlock_industry` |
| `ths-capital` | 同花顺公司资本运作 | ths | `capital_funding`, `capital_project`, `capital_transaction`, `capital_equity_summary`, `capital_equity_position`, `capital_ipo`, `capital_encumbrance`, `capital_release` |
| `kaipanla-themes` | 开盘啦题材库 | kaipanla | `theme_daily` |
| `kaipanla-theme-details` | 开盘啦题材库 | kaipanla | `theme_detail`, `theme_category`, `theme_stock`, `theme_stock_reason` |
| `ths-yuanhang-prices` | 远航版历史行情 | ths_yuanhang | `yuanhang_daily_price`, `yuanhang_price_year` |
| `ths-yuanhang-financial` | 远航版历史行情 | ths_yuanhang | `yuanhang_corporate_action`, `yuanhang_capital`, `yuanhang_series_proof` |
| `ths-yuanhang-limit-up-pool` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_pool`, `yuanhang_limit_member` |
| `ths-yuanhang-sprint-limit-up` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_pool`, `yuanhang_limit_member` |
| `ths-yuanhang-connect-broad-pool` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_pool`, `yuanhang_limit_member` |
| `ths-yuanhang-open-limit-up-pool` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_pool`, `yuanhang_limit_member` |
| `ths-yuanhang-limit-down-pool` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_pool`, `yuanhang_limit_member` |
| `ths-yuanhang-reason` | 远航版涨跌停分析 | ths_yuanhang | `yuanhang_limit_reason` |
| `tdx-hot-list` | 通达信个股龙虎榜 | tdx | `hot_list_day`, `hot_list_reason`, `hot_list_seat` |
| `tdx-margin` | 通达信个股融资融券 | tdx | `margin_security`, `margin_daily` |
| `tdx-industry-margin` | 通达信行业融资融券 | tdx | `industry_margin_day`, `industry_margin_daily` |
| `ths-market-margin` | 同花顺市场融资融券 | ths | `market_margin_series`, `market_margin_daily` |

## 实际存量逐表明细

“—”表示该统计未做或不适用；“日期为空”表示有记录但所统计的业务日期全部为空。日期两端不代表区间连续，不代表每个证券具有同样范围。证券数按本表 unified_code 去重，不把成员行数当成证券数。证明表与业务事实分开列出。

| 数据对象 | 行数 | 不同证券数 | 日期字段 | 已有日期最小值 → 最大值 |
| --- | ---: | ---: | --- | --- |
| `additional_issue` | 6,573 | 3,036 | `event_date` | 1998-06-26 → 2026-10-29 |
| `balance_statement` | 325,241 | 5,584 | `report_date` | 1989-12-31 → 2026-09-30 |
| `capital_encumbrance` | 99,290 | 3,273 | `event_date` | 2002-07-06 → 2026-10-31 |
| `capital_equity_position` | 21,921 | 2,154 | `event_date` | 2004-12-31 → 2026-06-30 |
| `capital_equity_summary` | 19,997 | 2,154 | `event_date` | 2004-12-31 → 2026-06-30 |
| `capital_funding` | 14,223 | 5,579 | `event_date` | 1987-01-01 → 2026-10-29 |
| `capital_ipo` | 123 | 123 | `event_date` | 日期为空 |
| `capital_project` | 63,751 | 5,576 | `event_date` | 1988-07-01 → 2026-10-31 |
| `capital_release` | 80,683 | 3,087 | `event_date` | 2002-07-06 → 2026-10-31 |
| `capital_transaction` | 254,563 | 5,501 | `event_date` | 0226-09-23 → 2026-11-03 |
| `cashflow_statement` | 326,289 | 5,584 | `report_date` | 1996-12-31 → 2026-09-30 |
| `dividend_plan` | 56,399 | 5,450 | `event_date` | 1991-06-08 → 2026-11-09 |
| `earnings_disclosure` | 264,815 | 5,581 | `report_date` | 2001-12-31 → 2026-09-30 |
| `earnings_forecast` | 109,203 | 5,528 | `report_date` | 2001-06-30 → 2026-12-31 |
| `earnings_quick` | 53,831 | 4,101 | `report_date` | 2004-06-30 → 2026-09-30 |
| `earnings_report` | 309,067 | 5,584 | `report_date` | 1989-12-31 → 2026-09-30 |
| `finance_news` | 61,536 | — | `published_at` | 2026-09-22 23:21:16 → 2026-11-02 19:38:37 |
| `holder_member` | 794,486 | — | `—` | — |
| `holder_report` | 69,581 | 5,583 | `report_date` | 2011-03-31 → 2026-11-30 |
| `hot_list_day` | 209,289 | 5,539 | `list_date` | 2002-08-02 → 2026-11-02 |
| `hot_list_reason` | 270,496 | 5,539 | `list_date` | 2002-08-02 → 2026-11-02 |
| `hot_list_seat` | 2,337,369 | 5,539 | `list_date` | 2006-07-03 → 2026-11-02 |
| `income_statement` | 336,933 | 5,584 | `report_date` | 1988-12-31 → 2026-09-30 |
| `index_daily_price` | 2,246,125 | — | `trade_date` | 1990-12-19 → 2026-11-02 |
| `index_price_year` | 9,598 | — | `—` | — |
| `industry` | 90 | — | `—` | — |
| `industry_margin_daily` | 78,810 | — | `trade_date` | 2016-01-04 → 2026-10-29 |
| `industry_margin_day` | 3,955 | — | `trade_date` | 2016-01-01 → 2026-10-29 |
| `industry_member` | 5,578 | 5,578 | `—` | — |
| `margin_daily` | 6,293,546 | 4,077 | `trade_date` | 2010-03-31 → 2026-10-30 |
| `margin_security` | 5,579 | 5,579 | `—` | — |
| `market_margin_daily` | 12,982 | — | `trade_date` | 2010-03-31 → 2026-10-30 |
| `market_margin_series` | 4 | — | `—` | — |
| `restricted_share_unlock` | 37,360 | 5,842 | `unlock_date` | 1996-05-10 → 2027-12-31 |
| `restricted_share_unlock_detail` | 364,818 | 5,842 | `unlock_date` | 1996-05-10 → 2027-12-31 |
| `restricted_share_unlock_industry` | 739 | — | `unlock_month` | 2026-09-01 → 2028-09-01 |
| `rights_issue` | 1,191 | 766 | `event_date` | 1990-03-01 → 2026-08-21 |
| `security_listing_event` | 556 | 420 | `event_date` | 1998-09-14 → 2026-10-28 |
| `security_name_change` | 11,923 | 2,727 | `event_date` | 1990-12-10 → 2026-10-30 |
| `security_st_event` | 3,952 | 1,106 | `event_date` | 1998-04-28 → 2026-10-23 |
| `shareholder_change` | 326,935 | 5,465 | `data_month` | 2002-07-01 → 2026-11-01 |
| `shareholder_count` | 232,561 | 5,581 | `statistics_date` | 2021-10-12 → 2026-10-30 |
| `stock` | 5,579 | 5,579 | `—` | — |
| `stock_index` | 573 | — | `—` | — |
| `stock_index_member` | 99,594 | 5,596 | `—` | — |
| `stock_listing` | 5,500 | 5,500 | `listing_date` | 1990-12-19 → 2026-11-03 |
| `stock_repurchase_plan` | 5,665 | 2,979 | `plan_date` | 2005-06-17 → 2026-11-02 |
| `suspension_event` | 104,771 | 4,407 | `suspended_at` | 2004-12-27 09:30:00 → 2026-11-02 09:30:00 |
| `suspension_source_date` | 145,401 | 4,407 | `source_date` | 2004-12-27 → 2026-11-02 |
| `theme_category` | 3,023 | — | `—` | — |
| `theme_daily` | 2,278 | — | `business_date` | 2026-10-25 → 2026-11-02 |
| `theme_detail` | 251 | — | `—` | — |
| `theme_stock` | 13,710 | 4,331 | `—` | — |
| `theme_stock_reason` | 15,951 | 4,331 | `—` | — |
| `trade_calendar` | 13,527 | — | `trade_date` | 1990-12-19 → 2027-12-31 |
| `trading_rule_citation` | 30 | — | `—` | — |
| `trading_rule_value` | 77 | — | `effective_start` | 2022-04-29 → 2026-07-06 |
| `yuanhang_capital` | 764,005 | 5,576 | `effective_date` | 1990-12-19 → 2026-11-02 |
| `yuanhang_corporate_action` | 57,688 | 5,434 | `ex_date` | 1991-02-26 → 2026-11-02 |
| `yuanhang_daily_price` | 17,033,204 | — | `—` | — |
| `yuanhang_limit_member` | 217,189 | 5,336 | `trade_date` | 2020-01-23 → 2026-11-02 |
| `yuanhang_limit_pool` | 43,770 | — | `trade_date` | 1990-12-19 → 2026-11-02 |
| `yuanhang_limit_reason` | 180,331 | 5,336 | `trade_date` | 2020-01-23 → 2026-10-30 |
| `yuanhang_price_year` | 75,987 | 5,576 | `—` | — |
| `yuanhang_series_proof` | 11,152 | 5,576 | `—` | — |

## 如何阅读边界

- 日历保存交易与休市日；行业两融日期头可包含有效空日；五池头可包含空集合。头表日期早于首条明细不表示漏采，也不能用早期空头证明源站历史能力。
- 题材列表现有日期从 2026-10-25 开始，详情是最新版本；本次未核查七日日内回放缓存。
- 解禁至 2027 年、行业解禁至 2028 年、未来上市日、未来分红日及股东报告期均按原业务日期列出，不等于未来事件已经发生或已可用于历史选股。
- 持有人报告、题材详情、行业指数成员、原始报表及交易规则各有来源质量和信息可用时间限制；详情参见用户数据清单和相应专项手册。

## 文档交付与验证

用户可见清单维护在[查看结果](../../src/empire/documentation/topics/desktop-results.md)，专项导航为[功能与数据范围](../../src/empire/documentation/topics/capabilities.md)。[原始汇总证据](data-inventory-2026-11-02.json)仅含聚合统计，不保存成功来源响应或业务明细全集。

本次只补正文与导航；已有市场两融、客户端等并发修改保留，不认领其实现或验收。本次未重打包、未重启客户端，已运行桌面内嵌帮助需后续正常构建才能包含新正文；不宣称已部署到当前窗口。

验证结果：正式聚合生成及检查通过（173篇）；显式文档审阅保留同期已有审阅说明和逐对象理由，新增本次数据清单审阅；`verify_documentation.py` 通过（526篇文档、3887个链接、68张正式结构表）。`test_documentation_build.py`、`test_documentation_contracts.py`、`test_collection_rules.py` 共38项通过（6.11秒）；逐项核对盘点覆盖全部52个登记任务。正式结构的68表包含配置、状态、代码映射，不等于本次采集任务对应的65表。

未执行真实桌面阅读或 `desktop/qa/help.cjs`：该脚本读取已有前端构建，不能证明本次尚未构建的正文。未运行采集、数据库写入或全项目测试；本次没有业务实现修改。同期五池收盘复核修改由其原记录负责，本次没有将其开发与发布验收算作数据盘点结果。
