<!-- topic:数据库参考|MySQL restricted_share_unlock -->
<!-- summary:大小非解禁完整月份市场的列表事实或共享股东明细，结构化字段和单事务集合证明。 -->
<!-- group:MySQL -->
# MySQL restricted_share_unlock

## 用途与归属

源码归属`features/unlocks`：`contract`定义字段，`dataset`事务保存，`query`提供正式读取；下载经唯一共享`sources/tdx_unlock.py`协议与公共下载/入队/归档服务。入口与存储身份保持，启动不迁移。

数据集unlocks.tdx_month，固定tdx，采集项目tdx-unlocks；统一归档与unlocks.tdx_query为唯一正式路径。

## 结构与身份

| 字段 | SQL类型与空值 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整来源事实及相同事实出现序号的SHA-256身份。 |
| `group_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券、解禁日期、来源原因代码的共享明细请求组；不等于独占列表事件ID。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源sc/code证券，沪深北统一身份。 |
| `unlock_date` | `DATE NOT NULL` | 列表T003解禁日期；不是公告可用日期。 |
| `reason_code` | `VARCHAR(128) NOT NULL` | 列表T006来源请求原因代码，明细请求必需。 |
| `name` | `VARCHAR(100) NULL` | 列表name来源简称，可空。 |
| `industry` | `VARCHAR(200) NULL` | 列表hyname来源当前行业，不代表历史行业。 |
| `reason` | `VARCHAR(1024) NULL` | 列表sT006或明细T006原因说明，可空。 |
| `shares` | `DECIMAL(28,8) NULL` | jjsl万股精确乘10000转股；未知NULL，0保留来源零。 |
| `total_shares` | `DECIMAL(28,8) NULL` | T010万股转股；仅来源提供比例基数，不保证解禁当日股本。 |
| `occurrence` | `SMALLINT UNSIGNED NOT NULL` | 相同规范事实的来源出现序号1～65535；允许合法重复。 |
| `detail_status` | `VARCHAR(16) NOT NULL` | present或source_empty；请求失败不能写成source_empty。 |
| `detail_count` | `INT UNSIGNED NOT NULL` | 共享请求组实际明细条数；并列列表不能据此倍乘明细。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务事实内容SHA-256。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本的观测时间，北京时间DATETIME(6)，不是来源公告时间。 |

- `PRIMARY KEY (record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_group (group_key,record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_security_date (unified_code,unlock_date,record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_date (unlock_date,unified_code,record_key)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_security CHECK (unified_code REGEXP '^[0-9]{6}\\.(SH|SZ|BJ)$')`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_shares CHECK (shares>=0 AND total_shares>=0)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_occurrence CHECK (occurrence BETWEEN 1 AND 65535)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_detail CHECK ((detail_status='present' AND detail_count BETWEEN 1 AND 10000) OR (detail_status='source_empty' AND detail_count=0))`：来源身份、数量或正式查询约束。

## 读写与关联

完整月市场两表及collection_state证明同事务提交；列表按record_key保留并列事实，明细按group_key共享；不能机械按列表行复制明细。列表200条稳定游标，明细请求组最多10000条。名称、行业和总股本基数可空，缺失名称不阻断普通分析；未知数量仍报告质量限制。仅新增、变化及撤回执行DML，相同内容零业务DML，可信摘要命中免SQL。

## 保留与恢复

每月完整响应校验后统一入队并继续下一月，仅整轮最后等待全部归档。明细失败不推进；来源有效空明细保留source_empty并在数据准备报告。迟到旧观测不覆盖；SQL后清队失败安全重放；成功相同及旧响应由公共归档清队。Redis丢失重新核验SQL范围，历史独立修订轮换回查。

## 维护与相关说明

scripts/create_unlock_schema.py显式新增两表；正常关闭Empire、队列0、持锁核对原业务及状态，启动不DDL。手工维护暂停归档并失效对应来源摘要/证明，规范或必需字段变更重新核验。

[大小非解禁个股与明细](help:大小非解禁个股与明细)
