<!-- topic:数据库参考|MySQL security_st_event -->
<!-- summary:通达信实施ST与撤销ST结构化来源事件，两个项目共表且独立核验。 -->
<!-- group:MySQL -->
# MySQL security_st_event

## 用途与归属

两个独立项目tdx-st-implementation和tdx-st-removal使用同一风险警示事件表。固定来源tdx，统一归档调用features/st_events/dataset.py，正式查询features/st_events/query.py；页面不写SQL，两个项目的状态与完整性证明仍独立保存。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `event_kind` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | implementation实施、removal撤销栏目；不裁定每日状态。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一代码、事件日期、前后简称及原因的SHA256身份。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源证券代码与SH/SZ/BJ市场，旧代码保留。 |
| `event_date` | `DATE NOT NULL` | rq来源实施或撤销日期，非公告日期。 |
| `old_name` | `VARCHAR(200) NULL` | prename前简称，NULL为未给。 |
| `new_name` | `VARCHAR(200) NULL` | lastname后简称，NULL为未给。 |
| `source_occurrences` | `INT UNSIGNED NOT NULL` | 本协议为1，同栏目证券日期重复拒绝。 |
| `csrc_industry` | `VARCHAR(200) NULL` | 证监会行业，无历史归属日期。 |
| `tdx_industry` | `VARCHAR(200) NULL` | 通达信行业，无历史归属日期。 |
| `reason` | `VARCHAR(2000) NULL` | ssyy来源原因，最长2000字符；NULL及空白规范为NULL，非空原样保留。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (event_kind, record_key)`
- `KEY ix_st_security (event_kind, unified_code, event_date, record_key)`
- `KEY ix_st_date (event_kind, event_date, unified_code, record_key)`
- `CONSTRAINT ck_event_kind CHECK (event_kind IN ('implementation','removal'))`
- `CONSTRAINT ck_st_occurrences CHECK (source_occurrences = 1)`
- `CONSTRAINT ck_st_old CHECK (old_name IS NULL OR CHAR_LENGTH(TRIM(old_name))>0)`
- `CONSTRAINT ck_st_new CHECK (new_name IS NULL OR CHAR_LENGTH(TRIM(new_name))>0)`

## 读写与关联

实施与撤销事件独立时间线、日期范围和排序，保留原始原因及多条记录；展示历史事件不推断当前ST状态。

以栏目及市场完整事务差异写入，业务与collection_state同事务；证券日期范围和日期全市场索引分别服务有界查询。历史不外键关联当前stock。相同内容无业务DML，可信摘要免SQL，迟到旧响应不覆盖；成功含无写入由统一归档删除Redis消息。

## 保留与恢复

保留来源当前返回的完整事件集合，修订替换对应栏目市场旧事实，不保留历次完整快照。Redis纯内存丢失后重新请求完整历史，依据SQL内容与证明核验，不保证恢复丢失队列。没有公告可用日期，不能自动还原每日ST状态。

## 维护与相关说明

正常关闭Empire，待归档0，通过scripts/create_st_event_schema.py预检及--apply显式建表；单实例及SQL锁保护，核对已有表数量、结构和状态摘要不变。启动不迁移、不删除旧业务。完整设计、容量和反例见docs/tdx-st-events.md。

[实施ST与撤销ST](help:实施ST与撤销ST)
