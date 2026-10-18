# 北交所历史证券代码映射

## 日常使用

本数据保存北交所官网“服务 → 新旧代码对照表”公布的全部换码关系。显式维护命令 `scripts/import_bse_code_mapping.py` 下载一次完整表，经集合校验、共享 Redis 入队和统一归档后保存到 MySQL。没有新增定时任务或改变开盘啦请求代码。后续需要更新时再次执行同一命令；相同内容不写业务表，已有历史关系不会因网页移除而删除。

来源：https://www.bse.cn/service/code_mapping.html 。这是发生换码的证券集合，不是全部当前北交所股票名单；直接使用920代码上市的证券没有可推断旧代码。上市日期按该表口径保存，精选层平移证券为原精选层挂牌日期，不代表北交所开市日。未公布换码生效日和ISIN，本表不生成这两项信息，也不据此声称开盘啦支持旧代码查询。

## 存储设计卡（实施前）

| 项目 | 设计 |
| --- | --- |
| 粒度 | `security_code_alias` 一行是一项北交所正式公布的旧代码到统一证券键关系；整份官方表为本次归档单位 |
| 身份 | 固定来源bse，主键legacy_code；unified_code唯一，保证该正式换码表一对一；不关联当前stock外键，退市不删除历史 |
| 字典 | legacy_code CHAR(6)旧代码；unified_code VARCHAR(9)新代码.BJ；name VARCHAR(100)来源证券简称；listing_date DATE来源上市日期；version_observed_at DATETIME最近实际变化版本的北京时间观测时刻，未变化不刷新 |
| 正式查询 | `SELECT * FROM security_code_alias WHERE legacy_code=:code` 或 `WHERE unified_code=:code`；分别命中主键/唯一索引，最多一行。全表按legacy_code有界读取，最多1000行 |
| 索引 | PRIMARY KEY(legacy_code)，UNIQUE KEY ux_alias_security(unified_code)；不建名称/日期索引，因为本次没有这些筛选用途 |
| 容量 | 当前官方表248项；契约单元最大1000项，预计五年不超过1000项，每行含索引保守512字节，业务不超过512KiB；隔离1000行放大测量，完整读取预算100ms、导入预算2秒、表索引合计预算1MiB |
| 完整性 | 表头精确匹配；完整table关闭及末尾官方日期口径注释；来源序号1到N连续；旧代码集合和新代码集合分别唯一；必需名称/日期合法；同条数不同集合反例；不根据后三位推算 |
| 版本 | 共享下载前生成带时区观测版本；统一状态保留微秒用于精确排序，业务表DATETIME写入前截断到秒，避免SQL舍入至未来误拒新响应；SQL同事务比较，旧响应不覆盖；完全相同零业务DML；冲突关系拒绝整份事务，禁止静默换绑；历史关系只新增、同身份元数据可修订，不删除 |
| 生命周期 | 显式命令一次下载整份，校验后入队；统一归档完成并清队才报告完成。下载失败不推进断点；SQL失败留队，SQL提交后重放安全。Redis丢失重新下载，历史映射在SQL保留 |
| 维护 | 新库init-db；现有库正常停机、待归档为0且持维护锁，通过create_security_alias_schema.py显式加表，核对已有表数量/DDL及统一状态不变；启动不迁移 |
| 正式路径 | 新数据集bse.code_mapping.complete，项目bse-code-mapping、任务bse-code-mapping-v1；共享下载/代理/频控→统一入队→统一摘要/SQL归档；本次只有显式导入入口，没有UI页面或计划任务 |

## 查询示例

```sql
SELECT legacy_code, unified_code, name, listing_date
FROM security_code_alias WHERE unified_code = '920149.BJ';
```

重复导入仍通过来源集合校验与统一归档。网页结构、代码集合或关系冲突报错后保留现有数据，不跳过坏行、不清空Redis、不清理未解决行情错误。
