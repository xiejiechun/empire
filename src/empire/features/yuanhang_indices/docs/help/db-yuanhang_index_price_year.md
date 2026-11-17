<!-- topic:数据库参考|MySQL yuanhang_index_price_year -->
<!-- summary:远航指数组件的yuanhang_index_price_year结构、身份和恢复边界。 -->
<!-- group:MySQL -->
# MySQL yuanhang_index_price_year

## 用途与归属

目录及日K固定来源ths_yuanhang，成分固定来源ths（同花顺网页）；三个独立任务，共用统一归档器，不保存成功响应或逐轮业务快照。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 六位同花顺指数身份，独立于股票代码；保留原生市场关联。 |
| `quote_year` | `SMALLINT UNSIGNED NOT NULL` | 年度身份，与日行及覆盖区间绑定。 |
| `native_market` | `CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源原生市场USHI、USZI或USTI，不能按代码猜测。 |
| `row_count` | `SMALLINT UNSIGNED NOT NULL` | 年度实际日期数量；不单独证明完整。 |
| `first_date` | `DATE NULL` | 年度最早实际来源日；无行NULL。 |
| `last_date` | `DATE NULL` | 年度最新实际来源日；无行NULL。 |
| `key_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 排序年度日期集合的SHA-256。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 排序日期及六项规范数值的SHA-256。 |
| `verified_through` | `DATE NULL` | 从当年1月1日连续权威覆盖截止；没有连续前缀为NULL。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 覆盖及字段契约版本，现为1。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 该年度最大归档观察版本的北京时间DATETIME；不冒充来源公布时刻。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code,quote_year)`
- `CONSTRAINT ck_yhi_year CHECK (quote_year BETWEEN 1900 AND 2100 AND row_count<=366)`
- `CONSTRAINT ck_yhi_year_dates CHECK ((row_count=0 AND first_date IS NULL AND last_date IS NULL) OR (row_count>0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date<=last_date))`

## 读写与关联

features/yuanhang_indices内归档与正式查询拥有唯一读写路径；业务与每项目collection_state同事务，完整键集合及内容摘要共同核验。目录和当前成分分页上限500，按证券反查有来源/统一代码索引；日K按指数日期及按日期跨指数分页。

## 保留与恢复

目录退出保留身份及历史行情，当前查询过滤active。明确暂无成分删除旧当前关系；失败不伪装空。日K NULL和异常原值保留，按日期版本合并防旧响应覆盖；历史覆盖在collection_state保存有界区间。Redis丢失从SQL可信覆盖恢复，不承诺恢复未归档消息。

## 维护与相关说明

仅scripts/switch_yuanhang_indices.py显式建表及退役用户授权的旧表，启动不迁移。维护须正常停机、队列清零、持有实例和数据库维护锁；DDL隐式提交按维护日志恢复。

[同花顺远航版A股指数](help:同花顺远航版A股指数) · [同花顺指数成分](help:同花顺指数成分) · [同花顺远航版指数日K](help:同花顺远航版指数日K)
