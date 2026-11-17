<!-- topic:数据库参考|MySQL yuanhang_limit_pool -->
<!-- summary:远航涨跌停分析结构化业务表，固定来源ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_limit_pool

## 用途与归属

五个日期池共享池头和成员，原因由独立证券日任务负责。固定来源ths_yuanhang；完整日期池或证券日原因是归档单元。不是运行日志，不与当前股票名单建立删除级联。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源查询交易日期，不从采集时刻推断。 |
| `pool_type` | `VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 五池来源策略标识。 |
| `source_total` | `INT UNSIGNED NOT NULL` | 来源完整集合总数；零不等于来源最早边界。 |
| `filter_text` | `VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 当前源过滤HS,GEM2STAR,ST；历史HS,GEM2STAR保留原口径，等待补采。 |
| `key_sha256` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范证券键集合SHA-256。 |
| `content_sha256` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整规范业务内容SHA-256。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 当前含ST口径版本2；历史旧口径版本1，不构成当前覆盖。 |
| `observed_at` | `DATETIME(6) NOT NULL` | 当前实际变化版本的北京时间观测时刻；无变化不刷新。 |

## 主键、索引与约束

- `PRIMARY KEY (trade_date,pool_type)`
- `KEY idx_yuanhang_limit_pool_kind (pool_type,trade_date)`
- `CONSTRAINT ck_yuanhang_limit_pool_count CHECK (source_total <= 10000)`
- `CONSTRAINT ck_yuanhang_limit_pool_filter CHECK (filter_text IN ('HS,GEM2STAR','HS,GEM2STAR,ST'))`

## 读写与关联

每日复盘整体行情按所选日核对涨跌停头数和实际成员数，一致才显示总数；0是已确认的真实空池，缺头或数量不一致显示缺值。首板与连板继续沿用正式交易日连续计算，不从N天M板文本推断。

日终归档拒绝未来日期，以及观察于查询当日北京时间15:30前的消息；盘中五池变化快照只存独立Redis键，不进入本表。收盘后重新请求并核验最终池，再由原统一归档路径写入；字段、唯一键和旧版本防覆盖规则不变。

统一归档器是唯一写入路径。池头与成员、状态同事务提交；修订仅改实际变化，重复内容零业务DML，较早观察版本不能覆盖更新核验。成功即清理对应Redis待归档消息，失败保留。SQL提交后重放不重复写业务。

五个日期池各自的近期维护与后续历史核验由唯一原项目分轮执行，共用本表、成员表及业务摘要；collection_state仅保留原项目状态，SQL归档核对该项目日期版本及池头版本，防止迟到旧响应覆盖。无新表或启动迁移。

当天池16:00至21:00每30分钟复核（含最后窗口），仍按完整日期池集合走同一归档路径；成员移出、移入及内容修订按实际差异更新，无变化不写业务表。只下载当天，不因此重采近期5日或历史日期；半小时完成窗口只保存在原Redis元信息，不新增SQL运行表。

日池列表最多200条、证券历史最多500条，按稳定业务键翻页；原因按证券日点查。数值保留DECIMAL(48,24)，超精度失败，不舍入。NULL与零不同，来源空池与未采集不同。

## 保留与恢复

已归档历史长期保留，不随证券退出当前股票名单删除。Redis丢失从SQL覆盖恢复，未归档单元须补采；来源空池不推定历史边界。

## 维护与相关说明

补充ST的显式维护入口scripts/migrate_yuanhang_limits_st.py，正常停机并停止归档后，核查队列无五池消息，其他项目消息原位保留；仅扩展过滤约束并失效五池摘要，核对已有业务及状态内容不变；不清除历史业务或盘中快照。新库建表入口scripts/create_yuanhang_limits_schema.py，先正常停机、核实队列及旧数据，再新增三表并校验。启动仅检查结构，不自动迁移；维护业务内容前须停止归档并失效相应摘要和完成证明。

操作与日期语义见[远航版涨跌停分析](help:远航版涨跌停分析)。

池成员按来源实际返回证券核验，含深圳退市板块37及市场编号151的北京A股历史旧代码；不能按当前股票名单或过滤标签丢弃成员。身份和时间0哨兵规则见[池成员](help:MySQL%20yuanhang_limit_member)。

市场复盘只读本表的日期范围数据，用于日历、涨跌停统计或题材轮动；不增加业务写入或缓存副本。参见[市场复盘](help:市场复盘)。
