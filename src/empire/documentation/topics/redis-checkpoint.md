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

远航金融的deferred按证券保存来源可用性证据：status区分deferred_prelisting上市前与deferred_initial_capital已上市初始股本尚未就绪，保留上市日、来源截止日、native_status、来源日期、节点及缺字段380/已见字段1、402、407，不保存响应正文。存在后者时整轮清队后phase为source_gap，不能冒充完整覆盖；同日同截止日复查由retry_deferred标记，只规划该集合，当前部分入队计划与位置仍原子恢复。补齐后删除对应证据；新日恢复正常每日核验，范围摘要变化拒绝隐式重绑。上述字段复用原键与公共CAS，Redis丢失后重新核实来源及正式库。

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

资本范围检查只读此键的scope_changed与phase；来源范围已变化且尚在fetch/awaiting_archive时不沿用旧完整证明。读取失败回SQL，不改断点或用户策略。

quote显式有限运行把最多50证券、起止日及本轮proxy_priority放入cursor.request，继续使用同一job_key及公共CAS。待归档范围不允许换成另一范围；完成范围不能授权不同范围短路返回，也不推进全池每周复核标记。无参数日常任务仍按原全池生命周期，有限运行不保存日常策略。

ths-holders-v1使用format=2游标，记录本轮started_at、必要单元数、已入队页数、扫描位置和来源缺口摘要，不存全股票清单或报告正文。空名债券已确认后不冻结扫描，真正失败保留未确认状态；等待归档阶段只在本轮末执行。旧游标通过scripts/migrate_holder_checkpoint.py在程序关闭且共享队列为零后备份及CAS重置，保留递增revision、SQL和历史；不支持启动隐式转换。

旧游标维护同时仅失效ths_holders/ths的统一指纹及到期索引，使下次必要页面更新回SQL确认并自然保存fingerprint_hash；不为补该字段提前请求、不删除业务数据或缺口，不影响其他来源缓存。否则旧证明缺绑定字段时，长期热缓存会使SQL确认日期持续落后，导致重复计划。

通达信按市场拆分的完整响应断点用 unit_base 保存该期开始前的计数与滚动摘要；来源变化后仅重建该期，历史页码不回退。旧断点缺少起点时须停机，通过精确归档证明链校验后显式补齐，不在运行时猜测或清空。
