<!-- topic:数据库参考|MySQL suspension_source_date -->
<!-- summary:停复牌来源记录与实际查询日历日期的多对多关联。 -->
<!-- group:MySQL -->
# MySQL suspension_source_date

## 用途与归属

停复牌来源记录与实际查询日历日期的多对多关联。

统一归档器调用 `datasets/suspensions.py` 写入；`data/suspensions.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `source_date` | `DATE NOT NULL` | 该完整来源记录实际出现的查询日期，关联停复牌身份；不是生效日。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `suspended_at` | `DATETIME(6) NOT NULL` | 来源停牌生效时刻，不能当作来源查询日历日。 |
| `resume_key` | `DATETIME(6) NOT NULL` | 复牌身份列；未知时固定 1000-01-01 00:00:00，与 CHECK 一致。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (source_date, unified_code, suspended_at, resume_key, record_key)`
- `INDEX ix_suspension_identity (unified_code, suspended_at, resume_key, record_key, source_date)`

## 读写与关联

来源月份日历查询按已归档来源日期关联事件；未取得来源证明时保持未知，不能从关联行不存在推断无记录。

source_date 前缀用于日历日查询；ix_suspension_identity 用于查同一事件的所有实际出现日。与 suspension_event 用 unified_code/suspended_at/resume_key/record_key 全身份关联，不能只关联证券和停牌时间。

与 suspension_event 同事务合并实际出现日，重复不写；没有证据须补采，不推断为无记录。

股息率的分母日证据按source_date及unified_code、suspended_at、resume_key、record_key完整关联，只用record_key会误关联其他证券或时段。空日须另有collection_state连续范围和盘后确认，不能以无行代替覆盖证明；本用途只读。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[历史停复牌](help:历史停复牌)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL suspension_event](help:MySQL%20suspension_event)

日频准备仍核对本表必需字段、完整来源日期和SQL连续覆盖；只读可信摘要仅补充同一已覆盖范围的实际确认时间，不修改本表、来源身份或覆盖日期。盘前证据不满足盘后目标，缓存不可用回SQL。
