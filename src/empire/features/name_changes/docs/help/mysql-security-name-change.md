<!-- topic:数据库参考|MySQL security_name_change -->
<!-- summary:通达信公司全称与股票简称更名来源记录，共表按类型区分。 -->
<!-- group:MySQL -->
# MySQL security_name_change

## 用途与归属

通达信公司全称与股票简称更名来源记录，共表按类型区分。

统一归档器调用 `features/name_changes/dataset.py` 写入；`features/name_changes/query.py` 提供正式查询。业务页面不直接写表，来源、完整性及恢复契约由同一业务包持有。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `name_kind` | `VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | company 公司全称、security 证券简称，两个采集项目共表但状态独立。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `event_date` | `DATE NOT NULL` | 来源更名事件日期；不是请求日期。 |
| `old_name` | `VARCHAR(200) NULL` | 来源旧名称，空值保留为 NULL，不补成当前名称。 |
| `new_name` | `VARCHAR(200) NULL` | 来源新名称，空值保留为 NULL。 |
| `source_occurrences` | `INT UNSIGNED NOT NULL` | 完整相同事件在来源响应中出现次数，用合计核对来源总数。 |
| `csrc_industry` | `VARCHAR(200) NULL` | 来源证监会行业标签，未提供历史生效时间。 |
| `tdx_industry` | `VARCHAR(200) NULL` | 来源通达信行业标签，未提供历史生效时间。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (name_kind, record_key)`
- `KEY ix_name_security (name_kind, unified_code, event_date, record_key)`
- `KEY ix_name_date (name_kind, event_date, unified_code, record_key)`
- `CONSTRAINT ck_name_kind CHECK (name_kind IN ('company','security'))`
- `CONSTRAINT ck_name_occurrences CHECK (source_occurrences BETWEEN 1 AND 29999)`
- `CONSTRAINT ck_name_old CHECK (old_name IS NULL OR CHAR_LENGTH(TRIM(old_name))>0)`
- `CONSTRAINT ck_name_new CHECK (new_name IS NULL OR CHAR_LENGTH(TRIM(new_name))>0)`

## 读写与关联

公司与证券更名查询支持日期范围及正反排序，分页游标保留同日记录键；候选可匹配旧名并保留完整市场身份。

name_kind/证券/日期及 name_kind/日期索引支持各自查询；公司同日不同组合记录保留，空名称不补当前值，source_occurrences 合计参与来源总数核对。

保留历史；公司同日不同名称组合分别保存，股票同日重复身份拒绝；不生成代码变更或 ST 状态。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/create_name_change_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[公司与股票更名](help:公司与股票更名)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
