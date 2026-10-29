<!-- topic:数据库参考|MySQL industry_margin_daily -->
<!-- summary:行业融资融券的日期与行业原始事实，明确亿元、万元和万股，正式查询按键稳定分页。 -->
<!-- group:MySQL -->
# MySQL industry_margin_daily

## 用途与归属

固定来源tdx，数据集industry_margin.tdx_day，任务tdx-industry-margin。每行是一个日期与来源行业名称的七项原始数值，不用个股计算值替代来源统计，不存完整业务JSON。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源请求日期，不是公布时间 |
| `industry_name` | `VARCHAR(64) COLLATE utf8mb4_bin NOT NULL` | hy，唯一来源身份；无行业代码或历史分类版本 |
| `lending_balance` | `DECIMAL(28,8) NULL` | rqye，融券余额，万元 |
| `financing_balance` | `DECIMAL(28,8) NULL` | T003，融资余额，亿元 |
| `financing_buy` | `DECIMAL(28,8) NULL` | T004，融资买入额，亿元 |
| `financing_repay` | `DECIMAL(28,8) NULL` | T005，融资偿还额，亿元 |
| `lending_sell` | `DECIMAL(28,8) NULL` | T007，融券卖出量，万股 |
| `lending_repay` | `DECIMAL(28,8) NULL` | T008，融券偿还量，万股 |
| `lending_volume` | `DECIMAL(28,8) NULL` | T006，融券余量，万股 |

- `PRIMARY KEY (trade_date, industry_name)`：一天一个行业来源记录，支撑日期全行业查询。
- `KEY ix_industry_margin_name_date (industry_name, trade_date)`：单行业日期范围查询。

## 读写与关联

features/industry_margin/dataset是唯一写入路径，与industry_margin_day同事务比较完整日期集合。只写变化行；有效修订仅替换该日期，旧观测不能覆盖新版本。query提供日期/完整行业名称筛选及最多200行稳定游标；审计每批31日期、每日期最多256行业。融资融券差值查询时计算，亿元减万元/10000，不重复存储。

## 保留与恢复

不依赖当前股票或行业目录，不因成员或名单改变删除历史。来源名称变化作为新的来源身份，不能擅自映射历史分类。空响应不能自动删除旧非空集合。Redis摘要丢失回SQL比较；提交后重放安全。归档成功清业务队列，失败保留；摘要、断点及有界记录继续由共享框架管理。

## 维护与相关说明

scripts/create_industry_margin_schema.py显式创建。人工修订必须停归档、失效摘要并重建日期头，修改后核对日期×行业键及内容，不能只看条数。

[通达信行业融资融券](help:通达信行业融资融券)
[MySQL industry_margin_day](help:MySQL%20industry_margin_day)

来源负值保留，不改成零；数据准备检查会标记来源质量失败，使用前须排除或明确处理。
