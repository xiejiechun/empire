<!-- topic:数据库参考|MySQL ths_index_member -->
<!-- summary:远航指数组件的ths_index_member结构、身份和恢复边界。 -->
<!-- group:MySQL -->
# MySQL ths_index_member

## 用途与归属

目录及日K固定来源ths_yuanhang，成分固定来源ths（同花顺网页）；三个独立任务，共用统一归档器，不保存成功响应或逐轮业务快照。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 六位同花顺指数身份，独立于股票代码；保留原生市场关联。 |
| `source_code` | `VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 网页原始五/六位证券编号；不强制映射沪深北股票。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NULL` | 可靠股票前缀对应的统一代码；基金、债券或不确定身份为NULL。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称，不是历史名称库。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code,source_code)`
- `KEY ix_thsi_security (unified_code,index_code)`
- `KEY ix_thsi_source_security (source_code,index_code)`
- `CONSTRAINT ck_thsi_member_code CHECK (source_code REGEXP '^[0-9]{5,6}$')`
- `CONSTRAINT ck_thsi_member_unified CHECK (unified_code IS NULL OR unified_code REGEXP '^[0-9]{6}[.](SH|SZ|BJ)$')`

## 读写与关联

features/yuanhang_indices内归档与正式查询拥有唯一读写路径；业务与每项目collection_state同事务，完整键集合及内容摘要共同核验。目录和当前成分分页上限500，按证券反查有来源/统一代码索引；日K按指数日期及按日期跨指数分页。

## 保留与恢复

目录退出保留身份及历史行情，当前查询过滤active。明确暂无成分删除旧当前关系；失败不伪装空。日K NULL和异常原值保留，按日期版本合并防旧响应覆盖；历史覆盖在collection_state保存有界区间。Redis丢失从SQL可信覆盖恢复，不承诺恢复未归档消息。

## 维护与相关说明

仅scripts/switch_yuanhang_indices.py显式建表及退役用户授权的旧表，启动不迁移。维护须正常停机、队列清零、持有实例和数据库维护锁；DDL隐式提交按维护日志恢复。

[同花顺远航版A股指数](help:同花顺远航版A股指数) · [同花顺指数成分](help:同花顺指数成分) · [同花顺远航版指数日K](help:同花顺远航版指数日K)
