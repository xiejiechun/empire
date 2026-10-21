<!-- topic:数据库参考|MySQL suspension_event -->
<!-- summary:通达信历史停复牌完整来源记录，不裁定唯一交易约束。 -->
<!-- group:MySQL -->
# MySQL suspension_event

## 用途与归属

通达信历史停复牌完整来源记录，不裁定唯一交易约束。

统一归档器调用 `datasets/suspensions.py` 写入；`data/suspensions.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |
| `suspended_at` | `DATETIME(6) NOT NULL` | 来源停牌生效时刻，不能当作来源查询日历日。 |
| `resumed_at` | `DATETIME(6) NULL` | 来源复牌生效时刻，未知为 NULL；未知记录独立保留。 |
| `resume_key` | `DATETIME(6) NOT NULL` | 复牌身份列；未知时固定 1000-01-01 00:00:00，与 CHECK 一致。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |
| `source_dates_known` | `BOOLEAN NOT NULL` | 是否保存来源实际出现日期证据；FALSE 需要补采，不能视为当天无记录。 |
| `suspension_type` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源停复牌类别。 |
| `source_note` | `VARCHAR(100) NOT NULL` | 来源说明，参与来源记录身份；并列说明分别保留。 |
| `reason` | `VARCHAR(500) NOT NULL` | 来源原因，参与来源记录身份；不同原因不相互覆盖。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, suspended_at, resume_key, record_key)`
- `CONSTRAINT ck_suspension_resume_key_v2 CHECK (resume_key=COALESCE(resumed_at,'1000-01-01 00:00:00'))`
- `INDEX ix_suspension_start (suspended_at, unified_code)`
- `INDEX ix_suspension_resume (resumed_at, unified_code)`

## 读写与关联

预览按来源日历月份和独立事件卡呈现，各条说明保留；日历来源日期与事件生效日期分别查询，不按生效日期猜来源出现日。

按来源日历查询时关联 suspension_source_date 的完整四列记录身份；按停复牌生效时刻可用起始/复牌索引。证券历史保留，不选一条并列来源记录覆盖其他。

未知复牌、不同复牌时刻/说明/原因分别保留；仅完全相同来源记录去重。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[历史停复牌](help:历史停复牌)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL suspension_source_date](help:MySQL%20suspension_source_date)
