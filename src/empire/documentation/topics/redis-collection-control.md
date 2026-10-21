<!-- topic:数据库参考|Redis collection-control -->
<!-- summary:任务运行副本与采集历史：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis collection-control

## 用途与归属

批量启停逐项调用正式任务控制命令，沿用本键的运行副本、next_due 和历史记录；不新增批量运行记录或断点路径，单项失败继续处理其余任务，停止后仍保留已有断点与待归档业务消息。

任务运行副本与采集历史。CollectionControl 在自身锁内原子 SET，任务页面通过控制命令操作；财报查询只读辅助展示任务状态。

`diagnostics/redis_evidence.py` 在现有值不超过 8 MiB 时只读并提取指定任务的阶段、计划、next_due 和活动信息；超限报告未完成，不改写运行状态。此记录不能证明运行中归档器的内存隔离状态。

## 结构与身份

键模板：`<namespace>:collection:control:v1`

类型：**String / JSON**。

jobs 按 task_id 保存 policy、next_due、active、last_status、error、notice；history 为结束运行记录。notice 为有界脱敏的来源限制，不保存业务正文。active 有 run_id、started_at、origin、fresh、baseline_revision；时间为内部绝对时间。

### jobs 参数

| 参数 | 用途 |
| --- | --- |
| policy.enabled | 是否允许新的手动或计划执行；暂停同时禁用计划。 |
| policy.mode | manual 仅手动；interval 完成后等待间隔；daily 北京时间每日执行。 |
| policy.interval_seconds | 每次结束后等待 1～2592000 秒（最多 30 天）；股票及日历预设 86400 秒，新闻预设 60 秒。旧分钟配置仅通过维护入口转换，不改变已有下次执行时间；运行时只接受秒。新任务使用插件推荐计划，已保存配置优先。 |
| policy.daily_time | HH:MM，初始 18:00，按北京时间解释。 |
| policy.request_retries | 单请求额外重试 0～100 次，初始 2，保留已有设置，下次运行生效；指数YYYY临时404也使用相同预算，其他来源默认规则不变。 |
| policy.use_proxy / policy.proxy_fallback / policy.archived | 代理优先 / 允许直连回退 / 已归档任务标记；默认代理与回退均 true，归档任务禁止新执行。 |
| next_due | 下次执行的 Unix 秒时间戳；手动或禁用时为 null。 |
| active | 当前执行或等待恢复的运行信息；无活动执行时为 null。 |
| last_status / error | 最近执行状态及错误摘要。 |
| notice | 最近轮次来源缺口说明；开始新轮次时清空，来源缺口结果保存限制及补采位置。 |

### active / history 字段

| 字段 | 含义 |
| --- | --- |
| run_id / task_id | 本次运行标识与所属采集项目；异常恢复复用运行标识。 |
| started_at / finished_at | 开始 / 结束的 Unix 秒时间戳；界面转为北京时间。 |
| origin / fresh | manual 手动或 schedule 计划；fresh 表示明确从头创建新批次。 |
| request | 仅支持该契约的采集任务可保存本次显式范围：quote为1～50个精确市场证券、起止日期及proxy_priority布尔；不改policy或SQL保存设置。恢复复用原请求，不能覆盖活动任务范围，结束后保留到有界历史。 |
| baseline_revision | 执行前游标版本，用于判断恢复时是否已推进断点。 |
| status / error / notice | complete、paused、error、source_gap 等结果；error 保存真正失败，notice 保存来源限制，均脱敏且最多4096字符。source_gap 仅在有效消息全部确认归档后使用，不代表完整覆盖，不能推进缺口断点。旧记录不补写。 |
| result | 结果摘要，如 snapshot_id、collected、expected_count、pages；结束、暂停和失败时补充已提供的显示字段，包括 completed_units、processed_units、total_units、total_months、当前位置、失败数与分类及暂无详情数。新增快照仅使用固定白名单标量和四类失败计数，字符串最长512字符，不复制游标或业务数组；返回结果中的同名值优先。旧记录不补造统计。 |

## 读写与关联

policy 从 app_setting 加载为运行副本；合法已保存值优先，不按重启覆盖用户策略。next_due 从任务结束后计算，同任务不重叠。运行历史不进入 ingest。

## 保留与恢复

无 TTL，每项目独立保留最近 100 条已结束采集记录；活动记录不占此配额。页面清空可删选定项目/全部已结束记录，不改 active、计划、断点或业务。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`collection/control.py`、`features/financial_statements/query.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[任务状态字段](help:任务状态字段)、[数据库职责与查阅](help:数据库职责与查阅)
