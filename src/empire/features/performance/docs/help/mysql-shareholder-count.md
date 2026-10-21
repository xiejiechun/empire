<!-- topic:数据库参考|MySQL shareholder_count -->
<!-- summary:通达信股东户数结构化日期和数值，当前版本有界单元归档。 -->
<!-- group:MySQL -->
# MySQL shareholder_count

## 用途与归属

holder_count.tdx_unit归属tdx-holder-count任务，固定来源tdx。features/performance/dataset.py唯一正式写入，features/performance/query.py正式只读查询，页面不写SQL。

## 结构与身份

业务身份：unified_code、statistics_date；record_key为该组合规范SHA256。

| 字段 | SQL声明 | 含义及单位 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 业务组合身份SHA256。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | sc/code规范证券代码，不外键级联。 |
| `name` | `VARCHAR(100) NULL` | 来源证券简称。 |
| `statistics_date` | `DATE NOT NULL` | 统计日；来源sT002，NULL保持未知。 |
| `holders` | `BIGINT NULL` | 股东户数（户）；来源T003，NULL保持未知。 |
| `average_float` | `DECIMAL(28,8) NULL` | 平均流通股（股/户）；来源T004，NULL保持未知。 |
| `holder_change_pct` | `DECIMAL(28,8) NULL` | 户数变化（%）；来源T005，NULL保持未知。 |
| `top_float_shares` | `DECIMAL(28,8) NULL` | 前十大流通持股（股）；来源T008，NULL保持未知。 |
| `top_float_pct` | `DECIMAL(28,8) NULL` | 占流通股（%）；来源T009，NULL保持未知。 |
| `top_shares` | `DECIMAL(28,8) NULL` | 前十大股东持股（股）；来源T010，NULL保持未知。 |
| `top_pct` | `DECIMAL(28,8) NULL` | 占总股本（%）；来源T011，NULL保持未知。 |
| `holder_change` | `BIGINT NULL` | 变化户数（户）；来源T012，NULL保持未知。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容SHA256，排除批次及观测时刻。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时刻，北京时间；同内容不刷新。 |

### 主键、索引与约束

- `PRIMARY KEY (record_key)`
- `KEY ix_security_date (unified_code,statistics_date,record_key)`
- `KEY ix_date (statistics_date,unified_code,record_key)`
- `CONSTRAINT ck_holders CHECK (holders IS NULL OR holders >= 0)`

## 读写与关联

证券/日期/记录键索引支持200条游标页、证券历史及详情点查。完整单元流式核对规范内容和键摘要，单单元最多80000行、总审计最多100万行。单元及范围证明位于每项目唯一collection_state；报告键为报告期|市场，户数键为统一证券代码。没有业务JSON或重复快照。较旧观测响应不能覆盖新版，相同零业务DML，可信摘要免SQL。

## 保留与恢复

按完整响应校验后拆市场发布，快报规范矩阵经有界zlib-json-v1无损压缩传输，解码最多8MiB且校验长度/条数/流结束；任何市场超共享512KiB则整期不发布。全部入队后等待整轮归档，不逐期等待；成功/相同/旧版确认统一清队，失败保留重放。历史撤回不删，数据准备暴露差异；Redis丢失重新核验，非持久保证。

## 维护与相关说明

scripts/init_tdx_performance.py显式新增五表，正常关闭、单实例锁、待归档为空并核对原业务数量，启动不迁移。字段及来源改变重建证明。隔离容量100000行/表，查询和完整性专项证据见docs/tdx-performance.md及带日期证据。

[通达信股东户数](help:通达信股东户数)

预告、快报和业绩报告均有来源提前声明的明日公告日期（2026-10-12观测到2026-10-13）。来源公告日期保留原值，不能作为已经公布的证明；历史信号检查标记限制，分析用途单独呈现。实际披露日和户数统计日仍严格校验不晚于响应观测日。
