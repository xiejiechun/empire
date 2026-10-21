<!-- topic:数据库参考|Redis archives -->
<!-- summary:归档运行记录：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis archives

## 用途与归属

归档运行记录。统一归档器调用 CollectionRecords 写入，运行记录页面通过只读分页查询。

## 结构与身份

键模板：`<namespace>:collection:archives:<project_id>`

类型：**List / JSON**。

每元素为归档记录：id、project_id、snapshot_id、status、started_at、finished_at、processed_count、written_count、error 等；processed 包括重复确认，不等于新增。

### 共同字段

| 字段 | 用途 |
| --- | --- |
| id | 唯一记录 ID，精确删除和去重依据。 |
| project_id | 所属采集项目，例如 sina-stocks；配额按项目独立计算。 |
| created_at | 记录创建时间，界面显示北京时间。 |
| version | 产生该记录时的应用版本。 |

### 归档字段

| 字段 | 用途 |
| --- | --- |
| snapshot_id | 关联列表发布批次；不意味着保留历史列表数据。 |
| status | complete 已完成、replayed 已确认重放、superseded 已被新批次替代、invalid 校验失败、failed 归档失败。 |
| started_at / finished_at | 归档尝试的开始和结束时间。 |
| processed_count | 本次成功核对的业务记录数；包括实际写入、内容相同确认和旧版本确认。 |
| written_count | 本次发生业务写入的记录数；为 0 时可能是内容相同、可信摘要命中或旧版本无需覆盖。 |
| error | 归档结果中的错误摘要。 |

## 读写与关联

最新在列表首；稳定记录 ID 用于重放替换和去重，增删同步 archives-revision。记录不是待归档业务，不复制成功正文。

## 保留与恢复

无 TTL，每项目最近 100 条；超量淘汰最旧记录。页面可按项目清空记录，业务表和 ingest 不变。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`collection/records.py`、`collection/record_query.py`、`pipeline/archive.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[归档与错误记录](help:归档与错误记录)、[数据库职责与查阅](help:数据库职责与查阅)
