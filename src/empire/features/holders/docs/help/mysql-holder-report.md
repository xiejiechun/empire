<!-- topic:数据库参考|MySQL holder_report -->
<!-- summary:持有人报告头，按来源身份和版本同事务比较，重复零业务写入。 -->
<!-- group:MySQL -->
# MySQL holder_report

消息schema5的来源缺口集合由source_gaps_digest认证并存于collection_state；本表只保留可识别报告。空名报告不构造report_key，不影响同证券有效报告入库。

## 用途与归属

统一数据集holders.reports含三个栏目，固定来源ths；三栏同事务写入holder_report/holder_member，collection_state每项目一行并保留各栏集合证明。features/holders/dataset.py唯一正式写入，features/holders/query.py按kind只读，页面不写SQL。

## 结构与身份

变动公告当期最多200人，退出名单最多200人，报告最多400成员；公告汇总未知，来源当期/退出比例及数量横线允许NULL；未来报告期保留原日期并按观察日标记质量限制，历史读取不自动清标；空名债券仍属身份缺口，未识别报告不入业务表，同证券其他可识别报告正常保存。定期来源汇总横线与数量/比例矛盾保留原值，由quality_flags区分质量异常。定期汇总比例受100.15及成员人数×0.005的舍入上界双重限制，个人比例仍不超过100。股票定期前十栏目可能超过十人，最多200人，按来源顺序完整展示并核验全部身份、数量及比例汇总。000065可含并列成员；000430的2026-03-31流通股东列11人且末两人数量不同，全部11人参与来源汇总。不推断扩展原因，不截取十行；重复身份或超过上限仍拒绝；汇总矛盾保留来源原值并标记质量异常。

报告身份为kind、unified_code、instrument_key、report_date、report_type；成员身份为报告键、分组和序号。姓名/来源ID/股份类型校验重复业务成员，不以行数相等替代集合证明。

| 字段 | SQL声明 | 含义及单位 |
| --- | --- | --- |
| `report_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 类别、证券、证券/债券身份、报告期、报告类型的规范SHA256。 |
| `kind` | `VARCHAR(24) NOT NULL` | 三种持有人报告的业务类别。 |
| `unified_code` | `CHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 发行人统一证券代码，不外键到当前股票池。 |
| `instrument_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 股票统一代码或来源债券名称的SHA256。 |
| `instrument_name` | `VARCHAR(200) NOT NULL` | 股票统一代码或页面债券名称，不推测债券改名身份。 |
| `report_date` | `DATE NOT NULL` | 来源标签报告期；不是公告日。 |
| `report_type` | `VARCHAR(16) NOT NULL` | periodic定期报告，change_notice部分变动公告。 |
| `total_quantity` | `DECIMAL(24,4) NULL` | 来源名单汇总数量（股/张）；变动公告或来源明确横线为NULL，不以明细合计替代。 |
| `total_quantity_scale` | `BIGINT NULL` | 来源汇总显示倍率1、10000或100000000；汇总未知时与数量、精度同时NULL。 |
| `total_quantity_decimals` | `SMALLINT NULL` | 来源汇总显示小数位0至4；汇总未知时与数量、倍率同时NULL。 |
| `total_ratio` | `DECIMAL(9,4) NULL` | 来源累计比例（%）；变动公告或来源横线为NULL，不以已知明细比例之和替代。 |
| `ratio_basis` | `VARCHAR(64) NOT NULL` | 比例分母的来源文字口径。 |
| `quality_flags` | `SMALLINT NOT NULL` | 来源质量位：1当期比例未知、2数量汇总矛盾、4比例汇总矛盾、8数量汇总未知、16比例汇总未知、32当期数量未知、64退出数量未知、128报告期晚于采集观察日；0未发现这些异常。归档重算并参与摘要，不证明页面业务前十完整。 |
| `member_count` | `SMALLINT NOT NULL` | 当前实际人数：定期股票1至200、债券1至10、公告1至200。 |
| `exit_count` | `SMALLINT NOT NULL` | 退出名单实际行数0至200。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 报告规范内容SHA256，排除观测时刻。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本的观测时间，北京时间；相同不刷新。 |

### 主键、索引与约束

- `PRIMARY KEY (report_key)`
- `KEY ix_security_date (kind,unified_code,report_date,report_key)`
- `KEY ix_date (kind,report_date,unified_code,report_key)`
- `CONSTRAINT ck_holder_report_kind CHECK (kind IN ('top_holders','float_holders','bond_holders'))`
- `CONSTRAINT ck_holder_report_type CHECK ((report_type='periodic' AND ((total_quantity IS NULL AND total_quantity_scale IS NULL AND total_quantity_decimals IS NULL) OR (total_quantity IS NOT NULL AND total_quantity_scale IS NOT NULL AND total_quantity_decimals IS NOT NULL))) OR (report_type='change_notice' AND total_quantity IS NULL AND total_ratio IS NULL AND total_quantity_scale IS NULL AND total_quantity_decimals IS NULL))`
- `CONSTRAINT ck_holder_totals CHECK (quality_flags BETWEEN 0 AND 255 AND (total_quantity IS NULL OR total_quantity>=0) AND (total_ratio IS NULL OR total_ratio BETWEEN 0 AND 100.15))`
- `CONSTRAINT ck_holder_counts CHECK (member_count BETWEEN 1 AND 200 AND (kind IN ('top_holders','float_holders') OR member_count<=10) AND exit_count BETWEEN 0 AND 200)`
- `CONSTRAINT ck_holder_precision CHECK (total_quantity_scale IN (1,10000,100000000) AND total_quantity_decimals BETWEEN 0 AND 4)`

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
