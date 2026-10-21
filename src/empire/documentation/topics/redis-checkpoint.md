<!-- topic:数据库参考|Redis checkpoint -->
<!-- summary:采集入队断点：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis checkpoint

## 用途与归属

采集入队断点。统一入队器拥有写入；采集器通过公共接口读取/比较 revision，归档器只读用于判断被替代的未完成批次。

`diagnostics/redis_evidence.py` 只读已登记 job_key 的 revision/cursor，先核对长度，cursor 超过 128 KiB 时明确截断；诊断不推进断点。

## 结构与身份

键模板：`<namespace>:checkpoint:<job_key>`

类型：**Hash**。

revision 为递增比较交换版本；cursor 为对应来源规范 JSON，记录业务批次、位置、范围与 phase。job_key 是来源生命周期身份，不等于页面 ID。

## 读写与关联

准入及隔离复核通过后与消息原子发布，失败不推进；支持显式无正文状态更新也通过公共 CAS。complete 表示入队结束，不能冒充 MySQL 已可查询。

## 保留与恢复

无 TTL；只重启应用且 Redis 仍运行可续跑。Redis 丢失后按 SQL 确认边界和来源规则重建；未归档断点不从 SQL 伪造。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`pipeline/ingest.py`、`pipeline/archive.py`、`features/capital_actions/query.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[采集断点](help:采集断点)、[数据库职责与查阅](help:数据库职责与查阅)


ths-index-prices断点保存最多1000指数代码、当前指数位置、下一个年份、last快照摘要及本轮页序；不保存日线正文。入队后继续下一年，整轮处理后才完成。恢复last快照改变时重新规划当前指数年份，Redis丢失读取SQL年度证明补缺。

分红@3断点保留组装后已入队证券位置、范围摘要和最终归档阶段，不保存报告期响应正文。报告期尚未完整组装时失败不推进；继续采集重取报告期集合。旧@1/@2断点须通过scripts/migrate_dividend_identity.py显式失效；SQL中的历史日期发现证明与内存断点分别管理，Redis丢失仍可复用有效SQL证明。
