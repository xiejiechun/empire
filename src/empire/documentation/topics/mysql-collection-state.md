<!-- topic:数据库参考|MySQL collection_state -->
<!-- summary:统一 SQL 已确认采集状态，每 namespace/project_id 一行。 -->
<!-- group:MySQL -->
# MySQL collection_state

## 用途与归属

统一 SQL 已确认采集状态，每 namespace/project_id 一行。

统一归档器通过 `infra/collection_state.py` 和 `collection_state_unit.py` 与业务写入同事务提交；采集恢复、数据准备及查询读取当前项目确认。

按项目诊断通过 `diagnostics/project.py` 只读指定 namespace/project_id 的 progress、coverage、契约版本及更新时间；每个 JSON 投影最多 128 KiB，超限明确标记截断，不读取完整 units 正文，不更新确认时间。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `namespace` | `VARCHAR(160) NOT NULL` | 配置/采集空间，取 redis.namespace；与业务来源不同。 |
| `project_id` | `VARCHAR(100) NOT NULL` | 已登记的采集项目 ID，每项目只保留一条状态。 |
| `source` | `VARCHAR(80) NOT NULL` | 来源标识；新闻逐行保留，项目状态与登记来源一致。 |
| `dataset` | `VARCHAR(80) NOT NULL` | 当前状态对应的数据集/归档契约标识。 |
| `payload` | `JSON NOT NULL` | 规范状态 JSON：progress 页/批次确认，publication 最后实际发布，coverage/observed 范围及月份确认，units/manifest 按数据集保存集合与版本；不存成功响应或运行历史。 |
| `updated_at` | `DATETIME(6) NOT NULL` | 该行最近实际内容更新时刻，MySQL DATETIME 按北京时间保存。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (namespace, project_id)`

## 读写与关联

股票 publication 与 stock 同事务；日历 observed 按月；单位型数据只读写当前 unit 并保留其他单位。progress 最高页不是整轮成功证明，必须确认本轮 Stream 无剩余业务消息。

与业务事务提交，只记录最近 SQL 回源确认；Redis 摘要命中不读写本表。不是逐轮运行记录，也不恢复之后的无变化核验上界或未归档断点。

同花顺持有人单位证明的source_gaps为最多100条来源身份缺口（kind、report_date、source_panel、reason）；定位不作为债券身份，未知债券正文不入库。债券栏目availability=source_gap，其他栏目可独立完整。消息schema5绑定缺口摘要，来源补齐后重新采集更新证明。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_collection_state.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[采集进度与运行记录](help:采集进度与运行记录)、[数据库职责与查阅](help:数据库职责与查阅)


财报解读新增五项目：units局部键支持规范统一证券（如000001.SZ）和季度报告期|市场（如2026-06-30|SZ），严格验证日期/证券格式后JSON_SET；既有SZ:000001格式继续用于原声明项目。每响应完整集合摘要和数量、manifest整轮范围分别保存，同内容不更新业务表。每项目仍仅一行状态，无成功响应副本。
