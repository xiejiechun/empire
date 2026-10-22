<!-- topic:数据库参考|MySQL stock_repurchase_plan -->
<!-- summary:固定东方财富回购方案当前版本，核心日期和金额结构化，说明有界且不保存整份JSON。 -->
<!-- group:MySQL -->
# MySQL stock_repurchase_plan

## 用途与归属

repurchases.page归属eastmoney-repurchases-v1任务，固定来源eastmoney；features/repurchases/dataset.py正式写入、features/repurchases/query.py正式只读查询，页面不写SQL。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `plan_id` | `VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源REPURCODE方案编号，字符串排序。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源SECUCODE证券统一代码。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源证券简称。 |
| `share_type` | `VARCHAR(80) NOT NULL` | 来源股份类别。 |
| `plan_date` | `DATE NOT NULL` | DIM_DATE初始方案公告自然日。 |
| `updated_date` | `DATE NOT NULL` | UPD来源更新日期，旧版本比较依据。 |
| `progress_code` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源实施状态代码，未知代码保持原值。 |
| `plan_updated_date` | `DATE NULL` | UPDATEDATE方案更新自然日。 |
| `actual_through` | `DATE NULL` | DIM_DATE3累计实际统计截止自然日。 |
| `notice_date` | `DATE NULL` | NOTICEDATE累计回购公告日。 |
| `start_date` | `DATE NULL` | 回购开始日。 |
| `end_date` | `DATE NULL` | 回购结束日。 |
| `finish_date` | `DATE NULL` | 来源回购完成日，不是注销生效日。 |
| `shareholder_notice_date` | `DATE NULL` | 股东大会结果公告日。 |
| `advance_date` | `DATE NULL` | 来源进展公告日。 |
| `plan_price_upper` | `DECIMAL(28,8) NULL` | 计划回购价格上限，元/股，NULL未知。 |
| `plan_price_lower` | `DECIMAL(28,8) NULL` | 计划回购价格下限，元/股，NULL未知。 |
| `plan_quantity_upper` | `DECIMAL(28,8) NULL` | 计划回购数量上限，股，NULL未知。 |
| `plan_quantity_lower` | `DECIMAL(28,8) NULL` | 计划回购数量下限，股，NULL未知。 |
| `plan_amount_upper` | `DECIMAL(28,8) NULL` | 计划回购金额上限，元，NULL未知。 |
| `plan_amount_lower` | `DECIMAL(28,8) NULL` | 计划回购金额下限，元，NULL未知。 |
| `actual_price_upper` | `DECIMAL(28,8) NULL` | 累计实际回购价格上限，元/股，NULL未知。 |
| `actual_price_lower` | `DECIMAL(28,8) NULL` | 累计实际回购价格下限，元/股，NULL未知。 |
| `actual_quantity` | `DECIMAL(28,8) NULL` | 累计实际回购股数（股），NULL未知。 |
| `actual_amount` | `DECIMAL(28,8) NULL` | 累计实际回购金额（元），NULL未知。 |
| `objective` | `MEDIUMTEXT NULL` | 回购用途，最大64KiB UTF-8，不推断注销。 |
| `remark` | `MEDIUMTEXT NULL` | 方案说明，最大64KiB UTF-8。 |
| `progress_remark` | `MEDIUMTEXT NULL` | 累计进展说明，最大64KiB UTF-8。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容SHA256，排除观测时刻。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时刻，北京时间；相同内容不刷新。 |

### 主键、索引与约束

- `PRIMARY KEY (plan_id)`
- `KEY ix_security_date (unified_code,plan_date,plan_id)`
- `KEY ix_plan_date (plan_date,plan_id)`
- `KEY ix_progress_date (progress_code,plan_date,plan_id)`
- `CONSTRAINT ck_repurchase_plan_price_upper CHECK (plan_price_upper IS NULL OR plan_price_upper >= 0)`
- `CONSTRAINT ck_repurchase_plan_price_lower CHECK (plan_price_lower IS NULL OR plan_price_lower >= 0)`
- `CONSTRAINT ck_repurchase_plan_quantity_upper CHECK (plan_quantity_upper IS NULL OR plan_quantity_upper >= 0)`
- `CONSTRAINT ck_repurchase_plan_quantity_lower CHECK (plan_quantity_lower IS NULL OR plan_quantity_lower >= 0)`
- `CONSTRAINT ck_repurchase_plan_amount_upper CHECK (plan_amount_upper IS NULL OR plan_amount_upper >= 0)`
- `CONSTRAINT ck_repurchase_plan_amount_lower CHECK (plan_amount_lower IS NULL OR plan_amount_lower >= 0)`
- `CONSTRAINT ck_repurchase_actual_price_upper CHECK (actual_price_upper IS NULL OR actual_price_upper >= 0)`
- `CONSTRAINT ck_repurchase_actual_price_lower CHECK (actual_price_lower IS NULL OR actual_price_lower >= 0)`
- `CONSTRAINT ck_repurchase_actual_quantity CHECK (actual_quantity IS NULL OR actual_quantity >= 0)`
- `CONSTRAINT ck_repurchase_actual_amount CHECK (actual_amount IS NULL OR actual_amount >= 0)`

## 读写与关联

plan_id来源稳定编号为业务键，unified_code不依赖当前股票列表外键。列表按证券/日期/状态使用复合索引，200行游标页不读长说明；详情主键点查。完整性审计200行游标核对规范内容、逐行摘要和collection_state完整集合。UPD加观测时刻排序，迟到旧响应不覆盖，完全相同无业务DML；可信摘要免SQL。正式业务没有JSON列，不存行情和重复展示别名。

末批在既有摘要桶中另声明coverage项（contract/count/digest；不是业务方案），与逐方案摘要共用归档事务、版本校验和期限。全源集合发生变化时，即使末批方案全部命中缓存，集合证明也会回SQL确认并更新既有collection_state.coverage；相同完整证明命中仍免SQL。业务表结构、主键及历史保留不变；准备仍逐行核对全SQL集合，不按数量或末页成功放行。

## 保留与恢复

每轮全量核验来源方案，历史方案保留，来源移除不会自动删除；当前版本不提供严格历史信号回放。采集页面按公共容量拆批入队，下载与归档独立推进，尾批后确认整轮。插入、更新、相同或旧版本成功均由统一归档器清理消息；失败保留。Redis丢失从头核验SQL既有历史，缓存不是永久真相。

## 维护与相关说明

scripts/create_repurchase_schema.py显式新增表，正常关闭Empire、待归档Stream为0并持有维护锁，核对原有业务数量及状态摘要不变；启动不DDL。更改必需字段后重建集合证明。容量实验50000行约152MiB、导入34.36秒，分页最高4.75ms；估算每年新增2000方案。详细设计及证据见docs/eastmoney-repurchases.md。

[股票回购](help:股票回购)
