<!-- topic:数据库参考|MySQL theme_detail -->
<!-- group:MySQL -->
<!-- summary:题材结构化业务表theme_detail；统一归档、重复零写入与旧版保护。 -->
# MySQL theme_detail

## 用途与归属

固定来源kaipanla，属于themes业务包。repository是唯一SQL读写路径，dataset声明摘要及版本，query提供正式查询。

## 结构与身份

| 字段 | 类型 | 含义 |
|---|---|---|
| `theme_id` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源主题材ID；每日表子题材为父ID_CID |
| `name` | `VARCHAR(128) NOT NULL` | 来源名称 |
| `brief` | `MEDIUMTEXT NOT NULL` | 最新简介，UTF-8最多65536字节 |
| `introduction` | `MEDIUMTEXT NOT NULL` | 最新介绍正文，UTF-8最多1MiB |
| `source_created_at` | `DATETIME(6) NULL` | 来源CreateTime秒转北京时间；0转NULL |
| `source_updated_at` | `DATETIME(6) NULL` | 来源UpdateTime秒转北京时间；0转NULL |
| `observed_at` | `DATETIME(6) NOT NULL` | 当前存储内容的采样时间，北京时间；不因重复内容刷新 |
| `content_sha256` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整规范题材内容SHA-256，包含关联集合及次数 |

主键：`theme_id`。


## 读写与关联

每日表按日期完整单元更新，保留跨日历史；详情四表按题材完整事务更新，只保留最新。正式页面单页最多200条，详情头最多1MiB正文。相同业务不做DML，可信摘要免SQL；旧版本不覆盖，失败保留待归档消息。
来源完整集合校验后才允许删除完整单元内撤回记录。原始成功响应不长期保留，统一collection_state保存项目确认，不另建逐轮运行表。

## 保留与恢复

日列表跨日长期保留，详情仅保留最新；Redis丢失后新采样恢复，不能重建丢失日内轨迹。

## 维护与相关说明

`scripts/create_theme_schema.py`预检，正常关闭Empire且队列为0后使用`--apply`；启动不DDL。维护前后核对原业务，禁止清空共享Redis。

[开盘啦题材库](help:开盘啦题材库)

正式约束与索引：

`PRIMARY KEY (theme_id)`
