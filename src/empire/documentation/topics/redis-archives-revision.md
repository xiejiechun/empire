<!-- topic:数据库参考|Redis archives-revision -->
<!-- summary:归档列表查询修订号：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis archives-revision

## 用途与归属

归档列表查询修订号。CollectionRecords 的 Lua 与 archives 同步维护，查询方读取判断列表是否变化。

## 结构与身份

键模板：`<namespace>:collection:archives-revision:<project_id>`

类型：**String / integer**。

新增、替换或实际清空时递增；无正文、无处理状态、无业务版本意义。

## 读写与关联

作为静止页面轮询优化，不能代替条目内容或 SQL 归档证明。

## 保留与恢复

无 TTL，每项目一值，清空列表后仍可保留修订号；Redis 服务重启与列表一起丢失。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`collection/records.py`、`collection/record_query.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis archives](help:Redis%20archives)、[数据库职责与查阅](help:数据库职责与查阅)
