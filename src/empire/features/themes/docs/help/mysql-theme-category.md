<!-- topic:数据库参考|MySQL theme_category -->
<!-- group:MySQL -->
<!-- summary:题材结构化业务表theme_category；统一归档、重复零写入与旧版保护。 -->
# MySQL theme_category

## 用途与归属

固定来源kaipanla，属于themes业务包。repository是唯一SQL读写路径，dataset声明摘要及版本，query提供正式查询。

## 结构与身份

| 字段 | 类型 | 含义 |
|---|---|---|
| `theme_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源主题材ID；每日表子题材为父ID_CID |
| `category_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源分类ID；直接关联股票时NULL |
| `parent_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL` | 父题材或父分类ID；根节点NULL |
| `name` | `VARCHAR(128) NOT NULL` | 来源名称 |
| `order` | `INT NOT NULL` | 分类展示顺序 |
| `plate_code` | `VARCHAR(32) NOT NULL` | 来源ZSCode原值，不猜对应指数 |
| `first_shelved_at` | `DATETIME(6) NULL` | 来源FirstShelveTime秒转北京时间；0转NULL |
| `updated_at` | `DATETIME(6) NULL` | 来源UpdateCacheTime秒转北京时间；0转NULL |
| `is_new` | `BIGINT UNSIGNED NOT NULL` | 来源IsNew非负整数 |

主键：`theme_id,category_id`。

索引`idx_theme_category_parent`：`theme_id,parent_id,order`，支持对应范围/身份查询。

## 读写与关联

每日表按日期完整单元更新，保留跨日历史；详情四表按题材完整事务更新，只保留最新。正式页面单页最多200条，详情头最多1MiB正文。相同业务不做DML，可信摘要免SQL；旧版本不覆盖，失败保留待归档消息。
来源完整集合校验后才允许删除完整单元内撤回记录。原始成功响应不长期保留，统一collection_state保存项目确认，不另建逐轮运行表。

## 保留与恢复

日列表跨日长期保留，详情仅保留最新；Redis丢失后新采样恢复，不能重建丢失日内轨迹。

## 维护与相关说明

`scripts/create_theme_schema.py`预检，正常关闭Empire且队列为0后使用`--apply`；启动不DDL。维护前后核对原业务，禁止清空共享Redis。

[开盘啦题材库](help:开盘啦题材库)

正式约束与索引：

`PRIMARY KEY (theme_id,category_id)`

`KEY idx_theme_category_parent (theme_id,parent_id,`order`)`
