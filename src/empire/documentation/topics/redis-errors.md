<!-- topic:数据库参考|Redis errors -->
<!-- summary:有界错误诊断样本：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis errors

## 用途与归属

有界错误诊断样本。共享 CollectionRecords 写脱敏错误，运行记录页面读摘要/详情；不是业务归档路径。

按项目诊断的 `diagnostics/redis_evidence.py` 复用现有记录查询脚本，最多返回 50 条摘要；正文须另给确切错误 ID，在现有最多 300 条记录内定位，输出最多 64 KiB。只读错误不视为已修复，也不会清理记录。

## 结构与身份

键模板：`<namespace>:collection:errors:<project_id>`

类型：**List / JSON**。

id、project_id、created_at、version、stage、error、request_url、status_code、metadata；body 最多 64 KiB，含 body_truncated/body_complete、observed_bytes、original_bytes、original_sha256、sample_sha256。提前中断时完整字节数/摘要为未知。

### 共同字段

| 字段 | 用途 |
| --- | --- |
| id | 唯一记录 ID，精确删除和去重依据。 |
| project_id | 所属采集项目，例如 sina-stocks；配额按项目独立计算。 |
| created_at | 记录创建时间，界面显示北京时间。 |
| version | 产生该记录时的应用版本。 |

### 错误字段

| 字段 | 用途 |
| --- | --- |
| stage / error | 出错阶段与具体原因。 |
| request_url / status_code | 脱敏请求地址和 HTTP 状态；非 HTTP 错误可为空。 |
| metadata | 页码、批次、消息位置等诊断元数据，保存前脱敏。 |
| body | 脱敏后的错误原文样本，每条最多 64 KiB；不是成功响应归档。 |
| body_truncated | 样本是否被截断；提前终止读取也标记为 true。 |
| body_complete | 是否完整读取原文；下载超限或提前终止时为 false，不等于样本未截断。 |
| observed_bytes | 实际已观察到的正文量，不推断未读取的完整长度。 |
| original_bytes | 完整读取时的原文字节数；body_complete=false 时为空，显示未知。 |
| original_sha256 | 完整读取时原始内容的 SHA-256；未完整读取为空，不能把前缀摘要当作完整摘要。 |
| sample_sha256 | 最终脱敏样本的 SHA-256，与原文摘要含义不同。 |

停复牌跨来源日期的同身份内容冲突在 metadata.conflict 中附 identity、source_dates 和 fields（每个差异字段的前后值）。该对象沿用公共元数据的深度、节点、文本及 8 KiB 序列化上限；超限明确截断。它是冲突诊断，不是成功响应存档或历史字段补录。旧记录缺少该对象时仍未知，不能从后续成功响应还原旧差异。

## 读写与关联

最新在首，确定 ID 替换同记录；与 errors-revision 原子更新。修复先登记项目/ID，先修复并验证，再按确切 ID 清理并记结果，保留并发新增和未解决项。

## 保留与恢复

无 TTL，每个项目最近 300 条；最旧超量淘汰。查看或一次采集成功不自动清理；用户日志清空属于记录管理，不代表故障修复。不写入 MySQL。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`collection/records.py`、`collection/record_query.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[日志清空与修复记录](help:日志清空与修复记录)、[数据库职责与查阅](help:数据库职责与查阅)
