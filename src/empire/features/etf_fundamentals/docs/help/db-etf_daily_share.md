<!-- topic:数据库参考|MySQL etf_daily_share -->
<!-- summary:ETF来源事实或内容绑定覆盖证明；明确身份、精确字段、版本与恢复边界。 -->
<!-- group:MySQL -->
# MySQL etf_daily_share

## 用途与归属

etf_fundamentals业务拥有；两所份额按来源共表，净值固定天天基金ttjj。证明表不是运行日志，项目状态只在collection_state。

## 结构与身份

| 字段 | SQL 声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | ETF统一代码，六位代码加.SH或.SZ；不级联当前目录。 |
| `share_date` | `DATE NOT NULL` | 来源份额业务日期，不是采样日。 |
| `source` | `VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 多来源身份sse或szse，与证券市场一致。 |
| `name` | `VARCHAR(128) NOT NULL` | 来源基金简称。 |
| `total_shares` | `DECIMAL(28,10) NOT NULL` | 精确总份额，单位份；SSE万份精确乘10000，SZSE直接取导出份。 |
| `source_group` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | SSE普通etf或交易货币money，SZSE固定etf。 |
| `source_type` | `VARCHAR(64) NULL` | 来源ETF_TYPE；未提供NULL。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 有效变更版本观测北京时间；相同内容不为刷新时间写库。 |

- `PRIMARY KEY (unified_code,share_date,source)`
- `KEY ix_etf_share_date (share_date,unified_code,source)`
- `CONSTRAINT ck_etf_share_code CHECK (unified_code REGEXP '^[0-9]{6}[.](SH|SZ)$')`
- `CONSTRAINT ck_etf_share_market CHECK ((source='sse' AND RIGHT(unified_code,2)='SH') OR (source='szse' AND RIGHT(unified_code,2)='SZ'))`
- `CONSTRAINT ck_etf_share_values CHECK (total_shares>=0 AND source_group IN ('etf','money') AND (source='sse' OR source_group='etf'))`

## 读写与关联

采集通过Redis统一归档在事务中修改事实、完整单元键/内容摘要及项目状态。任务内只读预览和复盘使用正式SQL，证券范围走主键、跨证券日查询走日期索引；每页默认200、最多500。没有对当前目录的级联删除。

## 保留与恢复

历史保留；相同内容零业务DML，迟到旧版本不覆盖。净值范围版本段含源端缺日期，阻止旧响应复活已撤回行。Redis摘要失效回SQL，提交后重放安全；运行记录和原始错误不入本表。

## 维护与相关说明

新空库由schema.sql，旧库经显式create_etf_fundamentals_schema.py持锁建表；停机、清队、前后业务核对，启动不迁移。来源/必需字段变化须显式失效相关覆盖及摘要。参考[ETF份额与净值](help:ETF份额与净值)。
