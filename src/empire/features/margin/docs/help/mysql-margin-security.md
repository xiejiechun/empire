<!-- topic:数据库参考|MySQL margin_security -->
<!-- summary:通达信个股融资融券的结构化存储、完整集合证明及唯一归档查询路径。 -->
<!-- group:MySQL -->
# MySQL margin_security

## 用途与归属

数据集margin.tdx_security，固定来源tdx，任务tdx-margin。margin_security保存证券完整响应证明，margin_daily保存证券交易日的七项原始数值，无业务JSON或成功原文。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券身份；无当前股票表级联删除 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整日期和全部规范数值SHA256 |
| `row_count` | `INT NOT NULL` | 来源完整记录数，0表示有效空响应 |
| `first_date` | `DATE NULL` | 来源最早日期，空响应NULL |
| `last_date` | `DATE NULL` | 来源最新日期，空响应NULL |
| `contract_version` | `INT NOT NULL` | 来源规范与集合证明版本 |

- `PRIMARY KEY (unified_code)`：业务身份、范围索引或完整性值域约束。
- `CONSTRAINT ck_margin_count CHECK (row_count >= 0 AND row_count <= 10000)`：业务身份、范围索引或完整性值域约束。
- `CONSTRAINT ck_margin_bounds CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date))`：业务身份、范围索引或完整性值域约束。

## 读写与关联

features/margin/dataset为唯一业务写入路径，证券完整历史同事务比较，只有变化行与变化证明写入。query提供每页200条稳定游标及每证券10000条审计，日期全市场和单证券范围均有索引；前一来源记录按索引读取，分页不改变页面派生公式。统一collection_state保存每证券SQL确认观测上界，Redis可信摘要命中免SQL。

## 保留与恢复

完整来源快照只替换该证券范围，来源退出行按完整快照更新；不因stock退市删历史。迟到旧观测不覆盖新版本，相同业务不刷新时间。Redis丢失保留SQL业务，下一轮重新全历史核验。SQL提交后重放安全；归档成功删除待归档消息，失败留队。

## 维护与相关说明

新增表通过scripts/create_margin_schema.py显式执行；停机、持锁、队列归零并核对原业务，启动不迁移。人工修改须停止归档、失效对应摘要并重建集合证明。

[通达信个股融资融券](help:通达信个股融资融券)
