<!-- topic:数据库参考|MySQL yuanhang_etf_daily_price -->
<!-- summary:ETF的yuanhang_etf_daily_price逐字段身份、索引及恢复字典。 -->
<!-- group:MySQL -->
# MySQL yuanhang_etf_daily_price

## 用途与归属

固定来源ths_yuanhang。ETF目录一证券一行；日K一证券一真实日期；年度表只存内容绑定证明，不重复存K线正文。业务先Redis，统一归档与项目collection_state同事务。

## 结构与身份

| 字段 | SQL声明（类型与空值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | ETF统一证券代码，六位加.SH/.SZ；独立于stock。 |
| `trade_date` | `DATE NOT NULL` | 来源字段1真实交易日期，不合成休市日。 |
| `open` | `DECIMAL(28,10) NULL` | 字段7开盘价，元；NULL未知。 |
| `high` | `DECIMAL(28,10) NULL` | 字段8最高价，元；NULL未知。 |
| `low` | `DECIMAL(28,10) NULL` | 字段9最低价，元；NULL未知。 |
| `close` | `DECIMAL(28,10) NULL` | 字段11收盘价，元；NULL未知。 |
| `volume` | `DECIMAL(28,10) NULL` | 字段13成交份额，份；不乘100，NULL未知。 |
| `amount` | `DECIMAL(28,10) NULL` | 字段19成交额，元；NULL未知，异常原值不填零。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code,trade_date)`
- `KEY ix_etf_price_date (trade_date,unified_code)`
- `CONSTRAINT ck_yhe_price_code CHECK (unified_code REGEXP '^[0-9]{6}[.](SH|SZ)$')`

## 读写与关联

features/yuanhang_etf拥有唯一规范化、归档和正式查询路径。证券身份独立于当前股票名单，不外键级联；目录最多5000只，年度最多150年×366日。分页默认200最多500；单证券日期范围走主键，单日全市场走日期索引。数值为DECIMAL(28,10)，不静默舍入。

## 保留与恢复

目录退出不删除历史。日K接受合法来源修订，按日期版本拒绝迟到旧响应，相同业务内容零DML；SQL后Redis失败安全重放，成功统一清队。覆盖状态每项目一条collection_state，按证券/年度保存合并区间；Redis丢失回SQL规划，不重下全部历史。

## 维护与相关说明

scripts/create_yuanhang_etf_schema.py显式创建三表；正常停机、队列清零、持实例及数据库维护锁，核对原业务不变。启动不执行DDL。

[同花顺远航版ETF目录](help:同花顺远航版ETF目录) · [同花顺远航版ETF日K](help:同花顺远航版ETF日K)
