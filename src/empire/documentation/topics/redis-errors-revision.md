<!-- topic:数据库参考|Redis errors-revision -->
<!-- summary:错误列表查询修订号：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis errors-revision

## 用途与归属

错误列表查询修订号。CollectionRecords 的 Lua 与 errors 同步维护；只读分页使用 known_revision 判断未变化。

`diagnostics/redis_evidence.py` 随错误摘要只读修订号，不递增它，不据此判断程序缺陷已经修复。

## 结构与身份

键模板：`<namespace>:collection:errors-revision:<project_id>`

类型：**String / integer**。

新增、替换、按精确 ID 实际移除或清空时递增；不保存错误正文、修复结果或业务版本。

## 读写与关联

无变化可返回未改变，详情仍按确切错误 ID 查询；不能用修订号声称所有故障已解决。

## 保留与恢复

无 TTL，每项目一值；列表清空后修订号可保留。Redis 重启后一同丢失。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`collection/records.py`、`collection/record_query.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis errors](help:Redis%20errors)、[数据库职责与查阅](help:数据库职责与查阅)
