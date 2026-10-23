<!-- topic:数据库参考|MySQL theme_stock_reason -->
<!-- group:MySQL -->
<!-- summary:题材结构化业务表theme_stock_reason；统一归档、重复零写入与旧版保护。 -->
# MySQL theme_stock_reason

## 用途与归属

固定来源kaipanla，属于themes业务包。repository是唯一SQL读写路径，dataset声明摘要及版本，query提供正式查询。

## 结构与身份

| 字段 | 类型 | 含义 |
|---|---|---|
| `theme_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源主题材ID；每日表子题材为父ID_CID |
| `relation_id` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整来源关联内容SHA-256；同证券多理由分别保留 |
| `category_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL` | 来源分类ID；直接关联股票时NULL |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 经核实的六位代码.市场，不按名称替换历史代码 |
| `reason` | `MEDIUMTEXT NOT NULL` | 来源理由，UTF-8最多65536字节 |
| `first_shelved_at` | `DATETIME(6) NULL` | 来源FirstShelveTime秒转北京时间；0转NULL |
| `updated_at` | `DATETIME(6) NULL` | 来源UpdateCacheTime秒转北京时间；0转NULL |
| `is_new` | `BIGINT UNSIGNED NOT NULL` | 来源IsNew非负整数 |
| `is_hot` | `BIGINT UNSIGNED NOT NULL` | 来源IsHot非负整数 |
| `source_is_zz` | `BIGINT UNSIGNED NOT NULL` | 来源IsZz非负整数，不擅自解释为布尔 |
| `occurrences` | `INT UNSIGNED NOT NULL` | 完全相同来源关联出现次数，1至50000 |

主键：`theme_id,relation_id`。

索引`idx_theme_reason_category`：`theme_id,category_id,relation_id`，支持对应范围/身份查询。
约束`ck_theme_reason_occurrences`：`(occurrencesbetween1and50000)`。

## 读写与关联

每日表按日期完整单元更新，保留跨日历史；详情四表按题材完整事务更新，只保留最新。正式页面单页最多200条，详情头最多1MiB正文。相同业务不做DML，可信摘要免SQL；旧版本不覆盖，失败保留待归档消息。
来源完整集合校验后才允许删除完整单元内撤回记录。原始成功响应不长期保留，统一collection_state保存项目确认，不另建逐轮运行表。

## 保留与恢复

日列表跨日长期保留，详情仅保留最新；Redis丢失后新采样恢复，不能重建丢失日内轨迹。

## 维护与相关说明

`scripts/create_theme_schema.py`预检，正常关闭Empire且队列为0后使用`--apply`；启动不DDL。维护前后核对原业务，禁止清空共享Redis。

[开盘啦题材库](help:开盘啦题材库)

正式约束与索引：

`PRIMARY KEY (theme_id,relation_id)`

`KEY idx_theme_reason_category (theme_id,category_id,relation_id)`

`CONSTRAINT ck_theme_reason_occurrences CHECK (occurrences BETWEEN 1 AND 50000)`
