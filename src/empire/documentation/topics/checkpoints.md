<!-- topic:技术参考|采集断点 -->
<!-- summary:核对采集断点的正式字段、规则和维护边界。 -->
# 采集断点

仅供排查采集恢复流程；断点只保存在 Redis 内存中。

## 股票列表


同花顺 `job_key=ths-universe-v1`、项目 `ths-stocks`。完整HTTP响应先验证集合，再以80条内部块入队；next_page是下次入队块号，不是再次请求的网页页码。digest保存规范集合SHA-256；恢复时只请求一次完整响应，摘要相同才续块，变化则建立新批次。complete表示全部块已入队，需等统一归档确认和本轮清队才完成。Redis丢失重新读取当前完整集合；SQL和共同stocks/current摘要阻止旧批次覆盖新目录。

新浪保留 `job_key=sina-universe-v1`，其来源分页断点如下：

| 字段 | 含义 |
| --- | --- |
| snapshot_id | 正在采集的列表批次标识，与发布身份关联。 |
| started_at | 本批次开始时间，带 UTC 时区。 |
| expected_count | 来源报告的预期股票数。 |
| page_size / node | 每页数量与来源节点；与续采配置必须一致。 |
| next_page / collected | 下一次请求页码与已入队股票数量。 |
| last_symbol | 上页最后一个来源代码，用于检查跨页排序。 |
| phase | pages 分页；verify 尾页和总数校验；complete 完成证据已入队，但不直接表示 MySQL 已提交。 |

## 财经新闻

新闻 `job_key=sina-news-v1`，项目 ID 为 `sina-news`。断点 `cursor` 字段：

| 字段 | 用途 |
| --- | --- |
| batch_id / started_at | 当前增量运行的标识与开始时间。 |
| phase | fetch 采集、awaiting_archive 等待归档、complete 已确认归档。 |
| before_id | 下一页只请求比该 ID 更早的条目，避免新增新闻造成偏移翻页漏项。 |
| high_watermark | 上次完成运行的最新新闻 ID；当前运行全部归档确认后才推进。 |
| upper_id | 本轮首条新闻 ID，作为新的增量上界。 |
| pages / collected | 已入队页数与处理条数。 |
| covered | 是否已接上上次增量断点。 |

若来源可见窗口已结束仍未接上断点，会保存 coverage 错误并停止，不能宣称无缺口。检查后使用“重新采集”可建立新的最新窗口基线；已有新闻不会删除。网页不是无限历史数据接口。

## 交易日历

项目 cninfo-calendar，job_key=cninfo-calendar-v1。`checkpoint` 的 cursor 字段：

| 字段 | 用途 |
| --- | --- |
| batch_id / started_at | 本轮标识与开始时间。 |
| months | 本轮实际请求的月份列表，包含历史缺月及本月至下一年年底。 |
| maintenance_start / end_month | 本轮本月和下一年 12 月；运行中保持固定，下一轮重新计算。 |
| pages | 已入队月数，也是 months 中下一月的索引。 |
| collected / expected_count | 已处理/预计处理的自然日数量，包含休市日。 |
| phase | fetch、awaiting_archive、complete；最后一个月提交后才完成本轮。 |

`archive:progress:cninfo-calendar-v1` 字段沿用新闻归档进度，page 代表本轮月份序号；Redis 进度缺失时可读取 collection_state 最近 SQL 确认进度。历史补采计划根据 SQL 完整性计算，即使 Redis 重启也跳过已完整的历史月份；未归档数据和下次执行时间会因 Redis 重启而丢失，计划配置仍保留于 MySQL。

没有额外来源参数，执行计划和 cninfo.com.cn 共享频率在采集管理统一设置。新任务默认手动，固定间隔预设 86400 秒（1 天）；从头重新采集会核验全部历史，普通采集只补缺及维护。

## 历史停复牌

项目 `tdx-suspensions`，job_key=`tdx-suspensions-v1`。业务表 `suspension_event` 主键为 `(unified_code, suspended_at, resume_key, record_key)`；不同复牌时间以及同一时间下不同来源说明/原因分别保留，未知复牌也不合并。字段如下：

| 字段 | 含义 |
| --- | --- |
| unified_code | 市场及证券代码的统一身份，如 `600001.SH`；来源固定为通达信。 |
| name | 来源证券名称；页面 market/code 从 unified_code 解析，不另存重复列。 |
| suspended_at / resumed_at | 北京时间停牌开始和可空复牌时间。 |
| resume_key | 复牌时间的非空主键表示；未知用内部 `1000-01-01` 占位，不作为业务复牌时间返回。 |
| record_key | 来源说明和原因的 SHA-256 身份摘要，仅用于分开通达信并列来源记录，不作为业务字段返回。 |
| source_dates_known | BOOLEAN，已知来源日期为真，旧记录未知为假，不能冒充当天无记录。 |
| suspension_source_date / source_date | 来源日期关联表；source_date 与事件完整键 unified_code、suspended_at、resume_key、record_key 组成主键。同事务并集合并，重复不写；跨日查询同一事件只显示一次。 |
| suspension_type | `full_day` 全天停牌或 `intraday` 盘中临停；来源明确同日复牌时按时间归为盘中停牌，即使文字写“停牌1天”，仍保留原说明。 |
| source_note / reason | 来源停复牌说明和原因。两项可选文字的 null/空白规范为空串，不编造说明、原因或时长；复牌时间未知仍为 null。 |
| version_observed_at | 当前入库存储版本的北京时间观测时间，用于防止旧响应覆盖。 |

每个自然月全部待采日期校验后优先成为一个增量归档页；超过入队字节上限则按连续日期拆分，按序入队继续采集，整轮结束才等待归档。来源记录和日期覆盖段分别建立摘要。旧主键通过 `scripts/migrate_suspension_identity.py` 显式迁移，原业务不删除，但重置本项目覆盖和断点以重查补回旧合并记录。

首次计划从 2004-12-27 到今天；普通计划从 `collection_state.payload.coverage.through` 当天重查到今天。cursor 保存起止日期、`period_index`、`resume_date`、`pages`、`dates_checked`、`collected` 和 `phase`；完整月份计划只在内存重建。应用重启直接从下一未发布日期继续，已有消息由归档器独立处理；未入队的月内下载需重采。Redis 重启从 SQL 覆盖上界当天重查。每批入队后继续采集，仅整轮入队结束后等待全部归档，公共确认排除本轮残留消息。请求共享 `tdx.com.cn` 频控组，固定间隔预设 86400 秒。
