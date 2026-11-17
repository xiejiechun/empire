<!-- topic:数据库参考|MySQL fx_price_year -->
<!-- summary:同花顺汇率完整年度覆盖证明，按品种及来源日期组织，不保存实时采样。 -->
<!-- group:MySQL -->
# MySQL fx_price_year

## 用途与归属

固定来源ths，数据集fx.price.year，所有者fx业务包；实时任务只有volatile准入归属，不能写本表。每行是品种乘年份完整性证明，与事实及collection_state同事务。

## 结构与身份

| 字段 | SQL 声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 固定十二品种标识加.FX；与股票身份分离。 |
| `quote_year` | `SMALLINT UNSIGNED NOT NULL` | 来源年份目录键，1900至2100。 |
| `source_count` | `SMALLINT UNSIGNED NOT NULL` | 该年份截止本轮已结束边界的来源条数。 |
| `row_count` | `SMALLINT UNSIGNED NOT NULL` | 事务后完整年度事实条数，必须等于source_count。 |
| `first_date` | `DATE NOT NULL` | 完整年度最早实际来源日期。 |
| `last_date` | `DATE NOT NULL` | 完整年度最晚实际来源日期。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整年度规范日期和OHLC的SHA-256，不包含观测时间。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 完整性证明规范版本，当前固定1。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 实际变更内容的观察版本，北京时间；重复确认不刷新。 |

- `PRIMARY KEY (unified_code,quote_year)`
- `CONSTRAINT ck_fx_year_count CHECK (source_count>=1 AND source_count<=366 AND row_count=source_count)`
- `CONSTRAINT ck_fx_year_range CHECK (quote_year>=1900 AND quote_year<=2100 AND first_date<=last_date AND contract_version=1)`

所有字段NOT NULL，无隐式业务默认；价格为正DECIMAL(20,10)，不舍入或补零。主键支持品种日期/年份查询；明细另有日期品种索引支持全品种日期范围，不外键到股票名录。

## 读写与关联

日线额外核验的年度须符合目录及原生当日行证明的日期边界，包含近期已有的已结束日期，且重叠OHLC一致；不能按接口名称选择冲突价格。日线不以实时报价昨收作为年度终值证明；已获取的完整年度复用于补缺，核验失败不发布该品种事实或更新本表。结构、摘要及版本比较契约不变。

来源目录可能先计入由原生当日行独立提供的当天槽位；完整年度缺这一未结束行时，须以实际日期证明合并计数，不能只放宽条数。原始年度已含当天但目录尚未计入时也只允许该确切尾部差额。随后按接收边界剔除全部未结束行，本表source_count只保存实际已结束条数，不把当日槽位冒充历史缺日或历史事实。

唯一写入路径为fx.dataset经统一入队/归档；查询fx.daily.query稳定游标每页最多500，完整年度最多366条，可通过正式history查询逐日期与OHLC审计。日线任务集中读取年度头及每品种SQL最近日期窗口，不在实时任务中回库。完整年验证后替换该年，近30日仅合并已证明集合；无变化不执行本表DML，来源修订仅修改受影响事实/证明。迟到旧版本不能覆盖，SQL提交后Redis失败可安全重放。

原生当日行身份、日期或价格无效时保留该品种原事实、年度证明和断点，不用实时报价、昨收或旧值替代。实时任务的明确空报价处理独立，不授权写入本表。

原生当日行仅作本轮边界核验，未结束时不进入事实或年度证明。多出或缺失已结束日期、重叠价格冲突仍拒绝；来源的当前行与历史行分别获取，不合成历史。跨响应失败记录原生当日行、有界计数、尾部和摘要以便诊断。

## 保留与恢复

跨接口核验冲突的品种不改本表证明，正常品种可独立完成归档。整轮有来源缺口时保留最早未完成品种断点；下一轮重核该后缀，可信已有年度仍按原覆盖规则使用，不能因其他品种成功刷新缺口的完整性证明。

MySQL长期保留来源历史，不按分钟保存。Redis丢失依年度证明及近期日期恢复；证明缺失/规范失配/近期日期集合消失触发完整年重取。详细审计需核对全年正文与摘要，不能仅以行数判断完整。较早历史修订经显式重新采集发现。

## 维护与相关说明

新增表仅用显式create_fx_schema维护入口，正常停机、队列清零、独占维护及前后其他业务核对；启动不建表。手工改SQL须停止归档、失效相关摘要和覆盖证明，不直接清Redis队列。用户入口见[同花顺汇率行情](help:同花顺汇率行情)。
