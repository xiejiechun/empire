# 交易规则与税费

本包负责七项已审核规则的来源解释、参数与引用、统一归档映射、正式查询及按需页面。`bundle.py` 是唯一贡献声明；原插件、任务、job、dataset、schema、页面身份及显式顺序槽保持，普通函数不注册插件。

| 修改目的 | 定位 |
| --- | --- |
| 参数身份、字段、单位和完整集合 | `contract.py`、`review.py`、`bse_review.py` |
| 官方目录、通知、附件与税费来源 | `sources.py`、`bse.py` |
| 有界HTML/PDF/DOCX解释及条款提取 | `documents.py`、`parameters.py` |
| 原子入队、失败及归档确认 | `collector.py` |
| 同事务参数/引用、摘要和旧版比较 | `dataset.py` |
| 游标分页、引用详情、范围和用途检查 | `query.py` |
| 市场筛选、按需条款与页面生命周期 | `ui.py` |

下载、代理、频控及有界预取仍由公共基础设施执行；统一入队/归档/摘要及SQL执行不在本包复制。每项单轮一份完整参数/引用批次，所有必要文件通过后才入队，失败不推进。五交易所输出复用一分钟解析缓存；初始化与后续均核验已审核当前文件，不自动解释新法规，不补造早期历史。Redis丢失后重核来源和SQL；相同、可信摘要和过时版本经统一归档成功清队，SQL后失败可重放。

沪深数值T+1、科创板递增数量、北交所涨跌价舍入及现行完整过户费/最低收费仍有用途缺口，不能把77参数集合完整称为全部准备通过。过户费保留新华社转述身份，北交所暂缓盘后条款不启用。

专项：`tests/test_trading_rules.py`、`tests/test_rule_documents.py`；全链路/恢复：`tests/integration/test_rule_archive.py`；私有工具守卫与取消：`tests/test_trading_rule_verification_tools.py`。安全实采入口`scripts/collect_trading_rules.py`使用独立13348、UUID SQL/Redis资源；容量入口`scripts/measure_trading_rules.py`保留77审核参数加10000压力行及原预算。均要求新build报告，不能用旧同名脚本写生产计划。规则按文件组采集，不适用逐股票随机30只门槛；仍须逐kind来源→队列→SQL→全部正式分页/引用核对，pending为0且清理完成。

用户操作、来源与日期限制见[交易规则说明](../../../../docs/trading-rules.md)，SQL对象字典见[数据库参考](../../../../docs/database-reference.md)。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
