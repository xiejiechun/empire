# A 股交易日历

`bundle.py` 贡献原有巨潮日历采集、查询、页面和数据集。`contract.py` 拥有来源起点、日期/月集合、规范行、摘要版本与已结束交易日规则；`collector.py` 复用共享下载、预取、统一入队和整轮归档确认。

| 修改内容 | 正式入口 |
| --- | --- |
| 规范月份和日期集合 | `contract.month_start/month_dates/months_between/validate_rows` |
| 同一连接内的最近已结束交易日 | `api.read_trade_day_cutoff(conn, now)` |
| 纯用途验收 | `audit_rules.audit_calendar` |
| 正式 SQL 月份快照 | `snapshot.calendar_snapshot` |
| SQL 与可选可信 Redis 证据合并 | `audit.py` |
| 统一归档、正式查询、页面 | `dataset.py`、`query.py`、`ui.py` |

公开截止日读取沿用 366 日 SQL 范围和北京时间 15:30 收市界限，使用调用方现有连接，不建立新事务。缺日期不能按周末推断，返回的未知状态仍须由调用方处理。停复牌覆盖时效是停复牌业务规则，归 `suspensions.coverage`，不混入通用日历契约。

日历验收先读完整 SQL 内容，再只读比对可用的 Redis 摘要、版本和到期索引。不可用缓存回到 SQL 证据；不为验收写回 SQL/Redis，也不让较新时间遮住缺日。完整月份、旧版保护、无变化不写业务 DML 和成功清队保持原正式路径。

验证入口为 `tests/test_calendar_preparation.py`、`tests/test_trading_day_cutoff.py`、日历采集/归档集成测试、`tests/test_foundation_public_api.py` 和统一装配身份检查。按月份业务核验，不能把证券随机30只机械当作日历验收。路径和规则归属迁移不构成新的实采或桌面验收证据。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
