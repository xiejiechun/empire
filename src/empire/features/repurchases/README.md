# 东方财富回购

本包按来源方案编号组织回购业务；同证券多方案分别保留。原插件、任务、数据集、页面、schema 与贡献顺序保持不变。

| 修改目的 | 入口 |
| --- | --- |
| 字段、日期、数值、来源分页校验 | `contract.py` |
| 请求、游标续采、原子入队与整轮确认 | `collector.py` |
| 规范消息、摘要与旧版本比较、SQL写入 | `dataset.py` |
| 只读分页、详情、全集合审计和用途准备 | `query.py` |
| 筛选、翻页与明细交互 | `ui.py` |
| 原身份及原槽位装配 | `bundle.py` |

公共依赖仍为共享下载/代理/限流、预取、统一入队、归档/摘要、SQLLane、QueryScope与页面控件，不在本包复制这些服务。查询只依赖MySQL。

初始化和后续均完整遍历全市场可见方案，REPURCODE字符串游标与剩余数严格核对；失败不推进。每批入队后继续下载，整轮入队结束才等待全部归档。Redis存活按已入队游标续采；丢失后从头核验，历史SQL保留。UPD及同日观测顺序阻止旧响应覆盖，同内容无业务DML。计划、累计实际和注销事实分别解释；当前修订版不支持严格历史信号回放。

末批的完整集合证明作为同一fingerprint桶的coverage项参与缓存比较与原SQL归档事务，前页修订而末页方案全热时仍更新原coverage；同内容及证明全热仍免SQL。payload、schema、表及任务身份均保持，旧缓存缺少此项按正常cache miss回SQL，不做运行时历史格式转换。准备标准不变：完整SQL键与规范内容必须匹配证明。

用户操作、字段、容量及限制见[来源说明](../../../../docs/eastmoney-repurchases.md)。领域与恢复：`tests/test_repurchases.py`、`tests/test_repurchase_ui.py`、`tests/integration/test_repurchase_archive.py`。安全工具专项为`tests/test_repurchase_verification_tools.py`。

真实验证使用`scripts/verify_repurchases.py`，显式独立测试实例及新build输出；共享资源生命周期/SQL守卫来自`source_verification.py`和`source_test_storage.py`。按方案全市场整轮核对，不宣称随机30股票。容量入口`scripts/measure_repurchases.py`要求本轮已通过来源证明`--source-proof`，复用相同私有资源保障；保留原50000行及全部原阈值。应用启动无DDL；现有显式建表维护入口仍为`scripts/create_repurchase_schema.py`。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
