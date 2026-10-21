<!-- topic:数据库参考|MySQL shareholder_change -->
<!-- summary:重要股东持股变动的结构化当前事实，完整月份市场版本保护与来源重复次数。 -->
<!-- group:MySQL -->
# MySQL shareholder_change

## 用途与归属

数据集shareholder_changes.tdx_unit，固定来源tdx，任务tdx-shareholder-changes，分类股东数据。唯一正式读写由完整单元数据插件与统一归档器执行。

## 结构与身份

| 字段 | SQL 类型与空值 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范事实及重复序号SHA-256身份；完整月份修订时允许改变。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券统一身份，固定来源通达信。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源证券简称。 |
| `data_month` | `DATE NOT NULL` | 请求月份第一天；验证变动截止日所属月份。 |
| `change_end` | `DATE NOT NULL` | 来源T003变动截止日。 |
| `change_start` | `VARCHAR(10) NULL` | 来源T013开始日期；严格保存YYYY-MM-DD或YYYY-MM精度，空值未知，不补造具体日。 |
| `announcement_date` | `DATE NULL` | 来源T004公告日；空或未来不证明当时已知。 |
| `actor` | `VARCHAR(512) NOT NULL` | 来源T005变动人。 |
| `price` | `DECIMAL(28,8) NULL` | 来源T006成交均价，元/股，可空。 |
| `shares_changed` | `DECIMAL(28,8) NULL` | 来源T007带符号变动数量，股；源端NULL保留并在质量检查限制使用。 |
| `shares_after` | `DECIMAL(28,8) NULL` | 来源T008变动后持股，股，可空。 |
| `reason` | `VARCHAR(512) NULL` | 来源T009变动原因，可空。 |
| `leader` | `VARCHAR(512) NULL` | 来源T010领导人姓名，可空。 |
| `position` | `VARCHAR(512) NULL` | 来源T011职务，可空。 |
| `relationship` | `VARCHAR(512) NULL` | 来源T012与领导人关系，可空。 |
| `occurrence` | `SMALLINT UNSIGNED NOT NULL` | 相同来源事实出现序号1～9999，不是稳定事件ID。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整规范业务行SHA-256。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时间，北京时间DATETIME。 |

- `PRIMARY KEY (record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_month (data_month,unified_code,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_security_date (unified_code,change_end,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_date (change_end,unified_code,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_month CHECK (DAYOFMONTH(data_month)=1 AND YEAR(data_month)=YEAR(change_end) AND MONTH(data_month)=MONTH(change_end))`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_dates CHECK (change_start IS NULL OR (change_start REGEXP '^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$' AND change_start<=CAST(change_end AS CHAR) COLLATE utf8mb4_unicode_ci))`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_shares CHECK (shares_after IS NULL OR shares_after>=0)`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_occurrence CHECK (occurrence BETWEEN 1 AND 9999)`：完整月份/证券/日期查询和来源契约约束。

## 读写与关联

完整月市场原子提交，collection_state同事务保存来源集合计数、摘要、契约及版本。主键是规范事实和重复序号；来源没有稳定事件ID。只写新增/变化事实并删除同月市场撤回事实；相同内容零业务DML，迟到旧响应不覆盖，缓存命中免SQL。

## 保留与恢复

保留其他月份历史，不保存完整旧版本。输入按整月一次10000、按市场压缩矩阵入队；来源计数/月份/重复次数校验通过才推进断点。全部入队后等待整轮归档。成功、相同及过时消息均由统一归档器清队，失败保留；Redis丢失重查正式范围。

## 维护与相关说明

scripts/create_shareholder_change_schema.py显式新增表，正常关闭桌面、队列0、持锁并核对原业务数量与状态。启动不迁移。手工修改前暂停归档并失效该来源摘要；必需字段或规范变更须显式重建证明。共享Redis已有键规则继续使用，不增加永久副本。

[通达信重要股东持股变动](help:通达信重要股东持股变动)
