<!-- topic:数据库参考|MySQL stock_index -->
<!-- summary:同花顺当前指数目录和成员可用性，一来源指数一行。 -->
<!-- group:MySQL -->
# MySQL stock_index

## 用途与归属

同花顺当前指数目录和成员可用性，一来源指数一行。

统一归档器调用 `datasets/indices.py` 写入；`data/indices.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 同花顺来源指数编号，六位字母数字字符串；不能默认当作股票代码。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |
| `source_group` | `VARCHAR(40) NOT NULL` | 来源目录分组名称，保留来源分类。 |
| `members_available` | `BOOLEAN NULL` | 成员可用状态：TRUE 可用、FALSE 来源暂无、NULL 尚未核验。 |
| `member_count` | `INT UNSIGNED NOT NULL DEFAULT 0` | 已确认的当前成员条数；不能证明历史覆盖。 |
| `member_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL` | 当前规范成员集合摘要，未确认可为 NULL。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code)`
- `CONSTRAINT ck_index_code CHECK (index_code REGEXP '^[0-9A-Z]{6}$')`
- `CONSTRAINT ck_index_members CHECK (member_count < 10000)`

## 读写与关联

目录与成员分页分离，成员统计来自正式查询；可带带来源指数身份进入日行情，证券反查使用完整统一证券匹配。

index_code 点查/当前目录浏览；成员使用 stock_index_member，member_count/member_hash 与完整当前成员集合一致，未核验/来源暂无不能当作有效空集合。

目录和单指数成员分别归档；只保留当前关系，不存每日快照。移除再加入须失效旧摘要重建成员。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/create_index_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[同花顺当前指数及成分](help:同花顺当前指数及成分)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_index_member](help:MySQL%20stock_index_member)


指数日行情查询及规划只读本表取得同花顺代码和显示名称；历史行情独立保存，目录移除不级联删除index_daily_price或index_price_year。相关操作见[同花顺指数历史日行情](help:同花顺指数历史日行情)。
