<!-- topic:数据库参考|MySQL trade_calendar -->
<!-- summary:巨潮自然日日历，交易与休市都显式保存。 -->
<!-- group:MySQL -->
# MySQL trade_calendar

## 用途与归属

巨潮自然日日历，交易与休市都显式保存。

统一归档器调用 `datasets/trade_calendar.py` 写入；`data/trade_calendar.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `is_trade` | `BOOLEAN NOT NULL` | 来源交易标记：1 交易日、0 休市日；缺行不是休市。 |
| `updated_at` | `DATETIME(6) NOT NULL` | 该行最近实际内容更新时刻，MySQL DATETIME 按北京时间保存。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (trade_date)`

## 读写与关联

按 trade_date 月范围读取完整自然日，空月/缺日明确未准备；observed 月份证明位于 collection_state，时效可使用匹配的 Redis 摘要辅助，普通查询无需 Redis。

按完整月事务比较，日期缺行代表未采集；相同日期不写，未来安排允许修订。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[交易日历](help:交易日历)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
