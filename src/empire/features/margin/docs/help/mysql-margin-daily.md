<!-- topic:数据库参考|MySQL margin_daily -->
<!-- summary:通达信个股融资融券的结构化存储、完整集合证明及唯一归档查询路径。 -->
<!-- group:MySQL -->
# MySQL margin_daily

## 用途与归属

数据集margin.tdx_security，固定来源tdx，任务tdx-margin。margin_security保存证券完整响应证明，margin_daily保存证券交易日的七项原始数值，无业务JSON或成功原文。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券身份；无当前股票表级联删除 |
| `trade_date` | `DATE NOT NULL` | 来源交易日期，不是公布时间 |
| `market_volume` | `DECIMAL(28,8) NULL` | bt009，万股，占比成交量分母 |
| `market_turnover` | `DECIMAL(28,8) NULL` | bt010，万元，占比成交额分母 |
| `close_price` | `DECIMAL(28,8) NULL` | ClosePrice，元，页面融券金额计算价格 |
| `financing_balance` | `DECIMAL(28,8) NOT NULL` | T003，万元，融资余额 |
| `financing_buy` | `DECIMAL(28,8) NOT NULL` | T004，万元，融资买入额 |
| `lending_balance` | `DECIMAL(28,8) NOT NULL` | T006，万股，融券余量 |
| `lending_sell` | `DECIMAL(28,8) NOT NULL` | T007，万股，融券卖出量 |

- `PRIMARY KEY (unified_code,trade_date)`：业务身份、范围索引或完整性值域约束。
- `KEY ix_margin_date (trade_date,unified_code)`：业务身份、范围索引或完整性值域约束。
- `CONSTRAINT ck_margin_values CHECK ((market_volume IS NULL OR market_volume >= 0) AND (market_turnover IS NULL OR market_turnover >= 0) AND (close_price IS NULL OR close_price >= 0) AND financing_balance >= 0 AND financing_buy >= 0 AND lending_balance >= 0 AND lending_sell >= 0)`：业务身份、范围索引或完整性值域约束。

## 读写与关联

features/margin/dataset为唯一业务写入路径，证券完整历史同事务比较，只有变化行与变化证明写入。query提供每页200条稳定游标及每证券10000条审计，日期全市场和单证券范围均有索引；前一来源记录按索引读取，分页不改变页面派生公式。统一collection_state保存每证券SQL确认观测上界，Redis可信摘要命中免SQL。

## 保留与恢复

完整来源快照只替换该证券范围，来源退出行按完整快照更新；不因stock退市删历史。迟到旧观测不覆盖新版本，相同业务不刷新时间。Redis丢失保留SQL业务，下一轮重新全历史核验。SQL提交后重放安全；归档成功删除待归档消息，失败留队。

## 维护与相关说明

新增表通过scripts/create_margin_schema.py显式执行；停机、持锁、队列归零并核对原业务，启动不迁移。人工修改须停止归档、失效对应摘要并重建集合证明。

[通达信个股融资融券](help:通达信个股融资融券)
