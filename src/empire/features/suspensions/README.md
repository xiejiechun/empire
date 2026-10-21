# 停复牌来源事件

`bundle.py` 贡献原有通达信停复牌采集、查询、页面和数据集。`contract.py` 集中业务身份、来源证券/时间规范、来源日期集合及期间校验；`collector.py`、`batches.py` 保留按序校验和共享发布流程。

| 修改内容 | 正式入口 |
| --- | --- |
| 来源记录身份、规范与期间规则 | `contract.py` |
| 日频用途的覆盖时效判断 | `coverage.coverage_as_of(coverage, now, cutoff)` |
| 行情范围的停牌日期排除 | `exclusions.excluded_days(rows, wanted, start, end)` |
| 正式 SQL 数据准备检查 | `audit.check_suspensions` |
| 归档、查询、页面与预览 | `dataset.py`、`query.py`、`ui.py`、`preview.py` |

公开排除函数接受已读取的来源记录，不查询数据库、不新建事务。保留未知复牌、不同复牌时间及并列说明/原因的记录，不合并成唯一回测约束；它与复权业务的 `suspended` 函数用途不同，不互相代替。`source_dates` 仍是来源响应出现日期，不能由停复牌生效时刻推断。

完整性、补采、旧记录关联日期修复、摘要规范版本、相同内容免业务 DML、旧响应拒绝和成功清队均沿用既有正式路径。缺少来源日期或日历证据须保持失败或未知，不能凭目录移动宣布准备完成。

验证入口包括 `tests/test_trading_day_cutoff.py`、`tests/test_market_suspension_days.py`、停复牌采集/归档回归、开盘啦停复牌范围集成测试和统一装配身份检查。新增/实改来源解析仍受共享代理随机30股及已知失败固定样本规则约束；本目录说明不证明已执行。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。

coverage.confirmed_coverage只读匹配的统一摘要补充已有SQL范围的观测时间，Redis失败回SQL；不伸展覆盖、不写SQL时间、不改采集或调度策略。盘前证据不能当盘后证明。
