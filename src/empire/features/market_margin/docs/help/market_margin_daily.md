<!-- topic:数据库参考|MySQL market_margin_daily -->
<!-- summary:同花顺市场融资融券结构化事实与完整序列证明。 -->
<!-- group:MySQL -->
# MySQL market_margin_daily

## 用途与归属

固定来源ths，任务ths-market-margin，数据集market_margin.ths_series。

## 结构与身份

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `market_code` | `VARCHAR(2) NOT NULL` | 来源市场99/3/2/4 |
| `trade_date` | `DATE NOT NULL` | 来源统计日，不是公布时间 |
| `financing_balance` | `DECIMAL(28,8) NOT NULL` | rzye融资余额元 |
| `lending_balance` | `DECIMAL(28,8) NOT NULL` | rqye融券余额元 |
| `financing_buy` | `DECIMAL(28,8) NOT NULL` | rzmre融资买入元 |
| `financing_net_buy` | `DECIMAL(28,8) NOT NULL` | rzjmr融资净买入元 |
| `lending_net_sell` | `DECIMAL(28,8) NOT NULL` | rqjmc融券净卖出股 |
| `financing_net_change` | `DECIMAL(28,8) NULL` | jmrzz融资净买入增减元 |
| `lending_net_change` | `DECIMAL(28,8) NULL` | jmczz融券净卖出增减股 |
| `balance_ratio` | `DECIMAL(38,24) NULL` | zb两融余额占流通市值小数比 |
| `source_total` | `DECIMAL(28,8) NULL` | lr合计来源总额元，分市场NULL |

- `PRIMARY KEY (market_code, trade_date)`
- `KEY idx_market_margin_date (trade_date, market_code)`

## 读写与关联

主键(market_code,trade_date)，日期索引(trade_date,market_code)。分页最多200，单市场最多10000日期；核心五值必需，负净值保留，NULL不当零。 相同内容零业务DML，观测版本在collection_state同事务保存，旧响应不能覆盖。完整来源缩短拒绝删除。显式scripts/create_market_margin_schema.py建表，启动不迁移。Redis仅暂存消息与公共摘要；归档成功即清消息。

## 保留与恢复

长期保留市场历史，Redis丢失重核完整市场；SQL与collection_state同事务，归档失败保留消息，成功即清队。

## 维护与相关说明

建表仅由显式维护入口执行。手工修改业务前停止归档并失效对应市场摘要及覆盖证明。

[同花顺市场融资融券](help:同花顺市场融资融券)
