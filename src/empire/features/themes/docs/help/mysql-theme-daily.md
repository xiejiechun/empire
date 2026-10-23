<!-- topic:数据库参考|MySQL theme_daily -->
<!-- group:MySQL -->
<!-- summary:题材结构化业务表theme_daily；统一归档、重复零写入与旧版保护。 -->
# MySQL theme_daily

## 用途与归属

固定来源kaipanla，属于themes业务包。repository是唯一SQL读写路径，dataset声明摘要及版本，query提供正式查询。

## 结构与身份

| 字段 | 类型 | 含义 |
|---|---|---|
| `business_date` | `DATE NOT NULL` | 北京时间采样自然日 |
| `theme_id` | `VARCHAR(65) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源主题材ID；每日表子题材为父ID_CID |
| `source_theme_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源主题材ID；请求详情使用本字段 |
| `concept_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL` | 子题材CID；主题材NULL |
| `name` | `VARCHAR(128) NOT NULL` | 来源名称 |
| `parent_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL` | 父题材或父分类ID；根节点NULL |
| `new_flag` | `INT UNSIGNED NOT NULL` | 来源新题材整数标记 |
| `rank_no` | `INT NULL` | 来源顺序计算排名；子题材/新题材NULL |
| `display_order` | `INT NOT NULL` | 完整目录展示顺序 |
| `hot_score` | `BIGINT UNSIGNED NULL` | 来源整数热度；子题材NULL |
| `change_rate` | `DOUBLE NOT NULL` | 来源binary32值以DOUBLE无损保存；显示百分比 |
| `limit_up_count` | `INT UNSIGNED NOT NULL` | 来源涨停数量 |
| `observed_at` | `DATETIME(6) NOT NULL` | 当前存储内容的采样时间，北京时间；不因重复内容刷新 |

主键：`business_date,theme_id`。

索引`idx_theme_daily_history`：`theme_id,business_date`，支持对应范围/身份查询。
索引`idx_theme_daily_rank`：`business_date,rank_no,theme_id`，支持对应范围/身份查询。
约束`ck_theme_daily_child`：`(((parent_idisnull)and(concept_idisnull)and(hot_scoreisnotnull))or((parent_idisnotnull)and(concept_idisnotnull)and(hot_scoreisnull)and(rank_noisnull)))`。

## 读写与关联

每日表按日期完整单元更新，保留跨日历史；详情四表按题材完整事务更新，只保留最新。正式页面单页最多200条，详情头最多1MiB正文。相同业务不做DML，可信摘要免SQL；旧版本不覆盖，失败保留待归档消息。
来源完整集合校验后才允许删除完整单元内撤回记录。原始成功响应不长期保留，统一collection_state保存项目确认，不另建逐轮运行表。

## 保留与恢复

日列表跨日长期保留，详情仅保留最新；Redis丢失后新采样恢复，不能重建丢失日内轨迹。

## 维护与相关说明

`scripts/create_theme_schema.py`预检，正常关闭Empire且队列为0后使用`--apply`；启动不DDL。维护前后核对原业务，禁止清空共享Redis。

[开盘啦题材库](help:开盘啦题材库)

正式约束与索引：

`PRIMARY KEY (business_date,theme_id)`

`KEY idx_theme_daily_history (theme_id,business_date)`

`KEY idx_theme_daily_rank (business_date,rank_no,theme_id)`

`CONSTRAINT ck_theme_daily_child CHECK ((parent_id IS NULL AND concept_id IS NULL AND hot_score IS NOT NULL) OR (parent_id IS NOT NULL AND concept_id IS NOT NULL AND hot_score IS NULL AND rank_no IS NULL))`
