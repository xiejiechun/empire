<!-- topic:数据库参考|MySQL yuanhang_limit_reason -->
<!-- summary:远航涨跌停分析结构化业务表，固定来源ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_limit_reason

## 用途与归属

五个日期池共享池头和成员，原因由独立证券日任务负责。固定来源ths_yuanhang；完整日期池或证券日原因是归档单元。不是运行日志，不与当前股票名单建立删除级联。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源查询交易日期，不从采集时刻推断。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 六位代码和SH/SZ/BJ后缀；不随当前股票名单裁剪。 |
| `name` | `VARCHAR(80) NULL` | 来源证券名称。 |
| `reason_text` | `TEXT NULL` | 原因正文，NULL、空串和非空正文分别保留。 |
| `reason_kind` | `TEXT NULL` | 原因分类栏目，独立保留缺值。 |
| `availability` | `VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | available或no_content；未采集没有记录。 |
| `content_sha256` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整规范业务内容SHA-256。 |
| `observed_at` | `DATETIME(6) NOT NULL` | 当前实际变化版本的北京时间观测时刻；无变化不刷新。 |

## 主键、索引与约束

- `PRIMARY KEY (trade_date,unified_code)`
- `KEY idx_yuanhang_limit_reason_security (unified_code,trade_date)`
- `KEY ix_yuanhang_reason_planning (trade_date,unified_code,observed_at,content_sha256)`
- `CONSTRAINT ck_yuanhang_limit_reason_availability CHECK (availability IN ('available','no_content'))`

## 读写与关联

ST补充后原因仍按五池证券日并集消重，沿用原单证券日详情接口；新增ST证券日会增加相应详情请求，不新增第二条原因归档路径。

日终归档拒绝未来日期，以及观察于查询当日北京时间15:30前的消息；盘中五池变化快照只存独立Redis键，不进入本表。收盘后重新请求并核验最终池，再由原统一归档路径写入；字段、唯一键和旧版本防覆盖规则不变。

统一归档器是唯一写入路径。每个证券日原因与本项目统一状态同事务提交，不要求与其他证券日或五池同步提交；修订仅改实际变化，重复内容零业务DML，较早观察版本不能覆盖更新核验。成功即清理对应Redis待归档消息，失败保留。SQL提交后重放不重复写业务。

原因按交易日和统一证券代码点查；覆盖规划使用日期、证券键及核验版本，正文只在详情或内容核验时读取。来源明确无内容保存no_content，与尚未采集缺行不同。两个原因栏目分别保留NULL、空串和实际文字。

## 保留与恢复

已归档历史长期保留，不随证券退出当前股票名单删除。Redis丢失从SQL覆盖恢复，未归档单元须补采；来源空池不推定历史边界。

## 维护与相关说明

显式维护入口scripts/create_yuanhang_limits_schema.py，先正常停机、核实队列及旧数据，再新增三表并校验。启动仅检查结构，不自动迁移；维护业务内容前须停止归档并失效相应摘要和完成证明。

操作与日期语义见[远航版涨跌停分析](help:远航版涨跌停分析)。

原因适用证券集合来自五池实际已归档历史成员，包含来源返回的北京A股旧代码及深圳退市板块37；不将历史代码映射为新代码，也不以当前股票表裁剪原因范围。

来源单栏目为NULL或空数组时均规范为该栏目NULL；另一个有正文或分类的栏目独立保留。两个栏目均未提供内容时availability为no_content；缺少约定栏目、多个证券行、错身份或多个无标签日期槽仍拒绝，不能当空成功。

原因接口有时以当前代码标记历史内容。已依据公司2025-028实施公告核实：2025-02-17之前请求300114.SZ而返回302132.SZ时，保留历史业务键300114.SZ，名称仍为来源返回名称（可能是当前名称）；不据此修改五池身份，也不推广到其他代码或变更生效后的旧代码。未经证明的错配继续失败。
