<!-- topic:数据库参考|MySQL yuanhang_index -->
<!-- summary:远航指数组件的yuanhang_index结构、身份和恢复边界。 -->
<!-- group:MySQL -->
# MySQL yuanhang_index

## 用途与归属

目录及日K固定来源ths_yuanhang，成分固定来源ths（同花顺网页）；三个独立任务，共用统一归档器，不保存成功响应或逐轮业务快照。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 六位同花顺指数身份，独立于股票代码；保留原生市场关联。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称，不是历史名称库。 |
| `native_market` | `CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源原生市场USHI、USZI或USTI，不能按代码猜测。 |
| `active` | `BOOLEAN NOT NULL` | 当前是否位于远航A股指数目录；退出保留历史身份。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code)`
- `CONSTRAINT ck_yhi_code CHECK (index_code REGEXP '^[0-9A-Z]{6}$')`
- `CONSTRAINT ck_yhi_market CHECK (native_market IN ('USHI','USZI','USTI'))`

## 读写与关联

features/yuanhang_indices内归档与正式查询拥有唯一读写路径；业务与每项目collection_state同事务，完整键集合及内容摘要共同核验。目录和当前成分分页上限500，按证券反查有来源/统一代码索引；日K按指数日期及按日期跨指数分页。

## 保留与恢复

目录退出保留身份及历史行情，当前查询过滤active。明确暂无成分删除旧当前关系；失败不伪装空。日K NULL和异常原值保留，按日期版本合并防旧响应覆盖；历史覆盖在collection_state保存有界区间。Redis丢失从SQL可信覆盖恢复，不承诺恢复未归档消息。

## 维护与相关说明

仅scripts/switch_yuanhang_indices.py显式建表及退役用户授权的旧表，启动不迁移。维护须正常停机、队列清零、持有实例和数据库维护锁；DDL隐式提交按维护日志恢复。

[同花顺远航版A股指数](help:同花顺远航版A股指数) · [同花顺指数成分](help:同花顺指数成分) · [同花顺远航版指数日K](help:同花顺远航版指数日K)
