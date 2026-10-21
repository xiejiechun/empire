<!-- topic:数据库参考|MySQL holder_member -->
<!-- summary:持有人结构化成员，按来源身份和版本同事务比较，重复零业务写入。 -->
<!-- group:MySQL -->
# MySQL holder_member

schema5隔离的未识别债券不生成本表成员；可识别报告仍逐成员比较与归档。重复采集不写成员，来源身份恢复后按正常报告键处理。

## 用途与归属

统一数据集holders.reports含三个栏目，固定来源ths；三栏同事务写入holder_report/holder_member，collection_state每项目一行并保留各栏集合证明。features/holders/dataset.py唯一正式写入，features/holders/query.py按kind只读，页面不写SQL。

## 结构与身份

变动公告当期最多200人，退出名单最多200人，报告最多400成员；公告汇总未知，来源当期/退出比例及数量横线允许NULL；未来报告期保留原日期并按观察日标记质量限制，历史读取不自动清标；空名债券仍属身份缺口，未识别报告不入业务表，同证券其他可识别报告正常保存。定期来源汇总横线与数量/比例矛盾保留原值，由quality_flags区分质量异常。定期汇总比例受100.15及成员人数×0.005的舍入上界双重限制，个人比例仍不超过100。股票定期前十栏目可能超过十人，最多200人，按来源顺序完整展示并核验全部身份、数量及比例汇总。000065可含并列成员；000430的2026-03-31流通股东列11人且末两人数量不同，全部11人参与来源汇总。不推断扩展原因，不截取十行；重复身份或超过上限仍拒绝；汇总矛盾保留来源原值并标记质量异常。

报告身份为kind、unified_code、instrument_key、report_date、report_type；成员身份为报告键、分组和序号。姓名/来源ID/股份类型校验重复业务成员，不以行数相等替代集合证明。

| 字段 | SQL声明 | 含义及单位 |
| --- | --- | --- |
| `report_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 类别、证券、证券/债券身份、报告期、报告类型的规范SHA256。 |
| `member_group` | `VARCHAR(8) NOT NULL` | current当前或exited上期退出名单。 |
| `seq` | `SMALLINT NOT NULL` | 组内规范行位置1至200；不是债券来源排名。 |
| `source_rank` | `SMALLINT NULL` | 债券页面原排名1至9999，可并列或缺口；股票NULL。 |
| `holder_name` | `VARCHAR(512) NOT NULL` | 来源持有人名称，最长512字符。 |
| `holder_id` | `VARCHAR(80) NULL` | 来源链接持有人标识，未提供为NULL。 |
| `quantity` | `DECIMAL(24,4) NULL` | 来源舍入显示数量换算为股/张，不承诺精确整数；横线未知与精度三字段同时NULL，不填零或推算。 |
| `quantity_scale` | `BIGINT NULL` | 来源显示倍率1、10000或100000000；数量未知时同时NULL。 |
| `quantity_decimals` | `SMALLINT NULL` | 来源显示小数位0至4；数量未知时同时NULL。 |
| `ratio` | `DECIMAL(9,4) NULL` | 来源持有比例（%）；当期或退出横线保存NULL，零仅来源明确零。当期NULL触发父头质量位1。 |
| `change_quantity` | `DECIMAL(24,4) NULL` | 来源增减量（股），符号按增减；未知为NULL。 |
| `change_label` | `VARCHAR(16) NULL` | 新进、不变或退出等来源标签。 |
| `actual_change` | `VARCHAR(128) NULL` | 实际增减持或变动比例的来源文字。 |
| `share_type` | `VARCHAR(128) NULL` | 来源股份类别，未提供为NULL。 |
| `pledge_ratio` | `DECIMAL(9,4) NULL` | 质押占直接持股比例（%），未知为NULL。 |
| `pledge_status` | `VARCHAR(64) NULL` | 无质押等来源状态文字。 |

### 主键、索引与约束

- `PRIMARY KEY (report_key,member_group,seq)`
- `CONSTRAINT fk_holder_report FOREIGN KEY (report_key) REFERENCES holder_report(report_key)`
- `CONSTRAINT ck_holder_member_group CHECK (member_group IN ('current','exited') AND seq BETWEEN 1 AND 200 AND (source_rank IS NULL OR source_rank BETWEEN 1 AND 9999))`
- `CONSTRAINT ck_holder_member_values CHECK (quantity>=0 AND (ratio IS NULL OR ratio BETWEEN 0 AND 100) AND (pledge_ratio IS NULL OR pledge_ratio BETWEEN 0 AND 100))`
- `CONSTRAINT ck_holder_member_precision CHECK ((quantity IS NULL AND quantity_scale IS NULL AND quantity_decimals IS NULL) OR (quantity IS NOT NULL AND quantity_scale IS NOT NULL AND quantity_decimals IS NOT NULL AND quantity_scale IN (1,10000,100000000) AND quantity_decimals BETWEEN 0 AND 4))`

## 读写与关联

时效缓存核对前后使用同一栏目内容摘要，SQL并发修订时不把新内容的确认时间用于此前已审计的旧内容。

准备汇总只在插件显式声明且选择分析用途时将来源质量异常标为有限制，不改写本表原值；字段损坏、身份和覆盖缺口保持阻断。

数据准备按所选证券的现行独立栏目证明读取本表，核对完整报告身份、成员集合、计数和规范摘要；来源窗口外历史仍保留，不将历史全集当作当前页面窗口。全市场缺口按当前股票池定位；整轮证明缺失不影响已独立核验的证券。

按类别/证券/日期或类别/日期/证券索引游标分页，最多100份报告头；报告键详情最多400成员。父头与成员同事务完整比较及修订；无业务JSON。当前窗口证明位于每项目唯一collection_state，包含有界证券/报告键、摘要、可用性和最终范围；正文审计批量20证券、每次10报告，总上限十万报告，超界明确报错。冷热回源同时核对父头当前/退出计数与实际成员集合，同日报告类型参与身份及稳定排序。成员规范顺序为current在前、exited在后，各按组内规范行位置；债券另存来源排名，允许并列和缺口，当期排名降序仍拒绝。

## 保留与恢复

保留已归档历史，来源窗口外报告不因未返回而删除。相同内容零业务DML；较旧观察不覆盖，可信摘要免SQL。所有成功处理由统一归档器清队，失败保留；SQL提交后Redis失败安全重放。来源无版本号，不提供完整历史版本回放。完整股东页面若仅含股东人数、十大股东、持股集中度区块，且十大股东有效、对应栏目及日期标签均不存在，可记录流通/债券栏目未提供；不是无持有人。残存标签、缺少必要区块或十大股东校验失败不能作为空栏目证明。

数量和比例保留来源舍入及口径；行内和汇总单位须与业务类型一致，显式基本单位覆盖表头显示倍率。公告没有完整前十汇总，债券缺序号保留并提示。

## 维护与相关说明

scripts/migrate_holder_source_rows.py显式升级来源行契约4：数量与显示精度三字段可同时NULL，未来报告期保留并标记；新增结构化quality_flags及允许来源当期比例/汇总未知，核对原事实及观测版本，保留业务并重建摘要；队列零、正常关闭桌面及维护锁后执行，覆盖和断点失效须重采。应用启动不迁移。scripts/create_holder_schema.py显式新增两表，正常关闭Empire、队列零和取得维护锁，核对已有业务数量/结构/状态。启动只校验，不迁移；兼容表复用，不覆盖不兼容结构。手工改SQL前停止归档并失效对应来源摘要。独立容量实验10000报告及110000成员，证据和生命周期见docs/ths-holders.md。

[同花顺前十大持有人](help:同花顺前十大持有人)







集合/摘要完整与来源数量/比例质量分别核验；源值不相互推导替代。来源质量异常不删除已有业务，修订正常清标；未知当期/退出数量与显示精度同时NULL，分别提示数量限制；未来报告期保留源日期并按请求观察日标记，历史读取不自动清标，新请求可确认修订。结构或日期格式错误仍失败；仅债券名称为空的报告按来源缺口隔离，其他可识别报告继续归档。
