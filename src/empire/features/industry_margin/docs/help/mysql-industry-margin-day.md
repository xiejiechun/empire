<!-- topic:数据库参考|MySQL industry_margin_day -->
<!-- summary:行业日期完整响应的聚合证明，同事务关联行业明细，区分有效空集合与缺失日期。 -->
<!-- group:MySQL -->
# MySQL industry_margin_day

## 用途与归属

固定来源tdx，数据集industry_margin.tdx_day，任务tdx-industry-margin。每行是一个来源日期完整行业快照的聚合头；不是采集运行日志。来源有效空集合保存row_count=0及空集合摘要，未采集日期无头。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 请求关联的来源统计日期；来源正文不回显日期 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 行业名称及七项规范事实的SHA256 |
| `row_count` | `INT UNSIGNED NOT NULL` | 完整行业条数，空集合为0 |
| `contract_version` | `INT UNSIGNED NOT NULL` | 规范契约及集合证明版本 |

- `PRIMARY KEY (trade_date)`：一天一份完整集合证明。
- `CONSTRAINT ck_industry_margin_count CHECK (row_count <= 256)`：完整日期容量上限。

## 读写与关联

features/industry_margin/dataset为唯一业务写入路径，日期头与industry_margin_daily在同一事务提交。无变化不更新业务表，不能为刷新观察时间重复写头。正式query按范围读取日期集合，审计以最多31天一批比较行业键、正文摘要及契约版本；缺头不解释为休市。

## 保留与恢复

保留2016年起来源返回的日期事实。SQL collection_state每项目一行，记录SQL确认版本与来源最新日期；Redis可信摘要命中免SQL。Redis丢失后依据日期头补缺，详细审计仍核对明细，不把最大日期当完整覆盖。SQL提交后重放不重复写，成功处理的业务消息由统一归档器删除。

## 维护与相关说明

scripts/create_industry_margin_schema.py为显式建表入口；停机持锁、队列归零并核对原业务，启动不建表。直接修改业务前停止归档、失效对应摘要并重建日期证明。

[通达信行业融资融券](help:通达信行业融资融券)
[MySQL industry_margin_daily](help:MySQL%20industry_margin_daily)
