# 通达信增发送配业务包

本包拥有分红送转、增发、配股三个独立采集任务、查询与页面；`bundle.py` 保留原声明、默认计划、数据集版本、身份和顺序。不会因为放在同一个包就合并三个业务生命周期。

| 修改内容 | 正式位置 |
| --- | --- |
| 证券、规范事件、业务键、版本和 rolling chain | `contract.py` |
| 日期、数值与来源业务错误 | `fields.py` |
| 原来源字段重建校验、增发详情契约 | `validation.py`、`issue_contract.py` |
| SQL记录→规范事件的公开纯解码 | `codec.py` |
| 请求身份常量与结果集结构协议 | `source_protocol.py` |
| 增发/配股列表解析、分红报告期/日期发现解析 | `parser.py`、`dividend_parser.py` |
| 来源下载、历史报告期、非季末日期发现、详情下载 | `source.py`、`dividend_history.py`、`dividend_discovery.py`、`issue_source.py` |
| 共用整轮生命周期、失败前沿、详情预取 | `lifecycle.py`、`recovery.py`、`issue_prefetch.py` |
| 三项采集插件 | `dividends_collector.py`、`issues_collector.py`、`rights_collector.py` |
| 唯一业务归档、内容比较、旧版保护与摘要贡献 | `dataset.py` |
| 正式有界查询、完整集合证明、详情复用候选 | `query.py`、`issue_candidates.py` |
| 唯一事件资格/歧义、公开错误与数值日期规则（复权共同使用） | `event_rules.py` |
| 只读名义派息、结果文字和分红页操作 | `distribution.py`、`distribution_text.py`、`ui_distribution.py` |
| 区间名义现金股息率及一致SQL快照输入 | `dividend_yield.py`、`yield_inputs.py`；复用上述分红证明与事件规则 |
| 页面、方案预览与字段文字 | `ui.py`、`preview.py`、`words.py` |

公开 `contract` / `fields` / `codec` 提供原有纯规范；跨业务读取方不借用采集执行或查询插件实现。`contract.validate_rows` 仍用现有源字段重建及详情校验，详情只依赖字段叶子模块，避免循环导入。所有来源URL、列名、过滤、数量口径、解析异常、资金单位与规范摘要算法保持原定义，不增加反射插件发现、兼容转发或第二归档路径。

数据集 `dividends.unit`、`additional_issues.unit`、`rights_issues.unit` 分别归档至 `dividend_plan`、`additional_issue`、`rights_issue`。原业务表及有界状态JSON保持；目录迁移不涉及DDL或存量转换，不执行显式维护脚本。所有下载/代理/频控、预取、Redis入队、事务恢复和成功清队仍复用公共框架。

来源生命周期、默认配置和用途以 [增发送配说明](../../../../docs/tdx-capital-actions.md)、[增发详情](../../../../docs/tdx-issue-details.md)、[详情可用性](../../../../docs/tdx-issue-availability.md) 为准。专项入口包括 `tests/test_tdx_dividends.py`、`tests/test_tdx_additional_issues.py`、`tests/test_tdx_rights_issues.py`、`tests/test_tdx_issue_details.py`、`tests/test_capital_lifecycle.py`、`tests/test_capital_recovery.py`、`tests/test_capital_preparation.py`、`tests/test_capital_ui.py`。端到端恢复见 `tests/integration/test_capital_archive.py`、`tests/integration/test_issue_availability_archive.py`、`tests/integration/test_prefetch_pipeline.py`；这些是定位入口，不代表本批已执行。

已有维护入口是 `scripts/migrate_dividend_identity.py` 与 `scripts/migrate_issue_availability.py`，仅在明确需要历史契约迁移时使用，正常目录移动无需运行。修改来源或生命周期语义须按 [采集开发指南](../../../../docs/collector-development-guide.md) 重新完成适用证券随机30及固定业务反例；报告期来源、详情与证券归档单位需要分别声明，不能把开发通过当作全市场已采完。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/dividends.md](docs/help/dividends.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。

本次用途范围专项：preparation.py只读核验现行SQL单元的精确业务键、内容和证明后投影日期；query.py接收既定PreparationScope。原全范围审计仍保留，完整历史失败不被局部范围覆盖。

P2在既有dividends.query登记dividend_yield；完整分红、日历、未复权quote及分母日停复牌由调用方同一RR READ ONLY事务核验。共享收盘时刻规则在kaipanla.closing，停复牌连接内公开检查为suspensions.query.closing_price_evidence。逐交易日股数基准变化、送转或必需输入缺失即阻断；名义派息产物仍可独立使用。没有新业务表、写库或第二计算规则。P3/P4仍未实现，验收见[本批账本](../../../../docs/evidence/shareholder-return-p2-2026-10-22.md)。
