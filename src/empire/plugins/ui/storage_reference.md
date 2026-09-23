<!-- topic:存储分工 -->
# 存储分工

**MySQL 保存三张业务表：`stock` 保留一份当前股票列表，`finance_news` 保留去重后的历史财经新闻，`trade_calendar` 保存交易和休市日期。成功 HTTP 请求原文不持久保存。**

有效响应解析、校验和规范化后，业务消息先进入 Redis。每 60 秒检查可归档批次，完整列表通过校验并在 MySQL 事务提交后，才确认并删除对应 Redis 消息。不完整批次继续留在 Redis；旧股票列表仍可查询。

三类记录分开，只留 Redis，不进入业务队列，不写入 MySQL：

| 记录 | 保留规则 |
| --- | --- |
| 采集记录 | 每个采集项目独立保留最近 100 条 |
| 归档记录 | 每个采集项目独立保留最近 100 条，独立于采集记录 |
| 错误记录 | 每个项目最近 300 条；每条脱敏原文样本最多 64 KiB，超出部分只保留长度与摘要 |

任务设置、必要断点和网站频控留在 Redis 内存中。只重启应用可续跑；Redis 服务或电脑重启会丢失未归档数据、断点、计划和记录。Redis 已关闭 AOF 和自动快照，没有关系型“表”，这里使用 String、Hash、Stream 和 LIST；键前缀由 `redis.namespace` 指定，通常为 `empire:dev`。

应用升级不自动迁移、重建或搬运数据库。结构调整需要显式执行针对性 SQL，保留当前业务数据并记录实际变更。不要清空共享 Redis 或删除其他项目数据。

<!-- topic:Redis 键与字段 -->
# Redis 键与字段

以下 `<namespace>` 来自 `redis.namespace`。

| 键 | 类型与用途 |
| --- | --- |
| `<namespace>:ingest` | Stream，字段 `envelope` 保存规范化业务消息，包括开始、分页和完成证据，不保存成功 HTTP 原文。完整批次提交 MySQL 后才 XACK / XDEL；不按长度裁剪未归档消息。 |
| `<namespace>:checkpoint:<job_key>` | Hash，内存断点。`revision` 为 CAS 并发版本，`cursor` 为业务游标 JSON；无 TTL，服务重启仍会丢失。 |
| `<namespace>:stocks:result:<source>` | 当前发布结果，`snapshot_id`、`status`、`row_count`、`expected_count`、`error_text`、`finished_at`、`started_at`；只留最新结果，不是历史快照库。 |
| `<namespace>:stocks:committed:<source>` | String / JSON，最新成功核验股票批次。保存 result 字段及 started_at；相同列表不写 SQL 时仍推进此标记，防止迟到旧批次覆盖。 |
| `<namespace>:archive:progress:<job_key>` | String / JSON，新闻或日历最新归档进度。`batch_id`、`page`、`status`、`row_count`、`error_text`、`observed_at`；SQL 提交后更新，供采集器确认归档，旧消息重放不回退新进度。 |
| `<namespace>:archive:observed:calendar.month:<source>` | Hash，字段为 YYYY-MM，值为最近成功核验该月的 UTC 观测时间。相同内容只更新这个内存标记；早于该观测的月消息跳过写库，防止旧版倒退。 |
| `<namespace>:collection:control:v1` | String / JSON，任务配置、活动执行状态及按项目限量的采集记录。 |
| `<namespace>:collection:archives:<project_id>` | LIST，每项目最近 100 条归档记录，不归档。 |
| `<namespace>:collection:errors:<project_id>` | LIST，每项目最近 300 条错误记录及有界原文样本，不归档。 |
| `<namespace>:collection:site-intervals:v1` | String / JSON，网站组到请求间隔毫秒数的映射；界面保存值覆盖 TOML 初始值。 |
| `<namespace>:rate:<group>` | Hash，共享频控。`next` 是下次发送许可的 Redis 毫秒时间戳，`cooldown` 是服务器冷却截止时间。 |

当前归档器按有界次数使用 XRANGE 扫描 Stream，Stream 本身保存待处理进度。保留 `archive` 消费组用于兼容旧队列；PEL 是旧领取流程可能遗留的内部元数据，不是当前独立暂存库。完成后 XACK / XDEL 一并清理。完整股票批次仍未齐全时继续保留队列，当前 SQL 股票列表不变。

## 股票列表断点 cursor

`job_key` 为 `sina-universe-v1`。

| 字段 | 含义 |
| --- | --- |
| snapshot_id | 正在采集的列表批次标识，与发布身份关联。 |
| started_at | 本批次开始时间，带 UTC 时区。 |
| expected_count | 来源报告的预期股票数。 |
| page_size / node | 每页数量与来源节点；与续采配置必须一致。 |
| next_page / collected | 下一次请求页码与已入队股票数量。 |
| last_symbol | 上页最后一个来源代码，用于检查跨页排序。 |
| phase | pages 分页；verify 尾页和总数校验；complete 完成证据已入队，但不直接表示 MySQL 已提交。 |

<!-- topic:采集记录与任务参数 -->
# 采集记录与任务参数

`collection:control:v1` 的顶层是 `jobs` 和 `history`。`jobs` 按任务 ID（例如 `sina-stocks`）管理；`history` 按 `task_id` 分别保留每项目最近 100 条，项目之间不会互相挤占配额。

## jobs 参数

| 参数 | 用途 |
| --- | --- |
| policy.enabled | 是否允许新的手动或计划执行；暂停同时禁用计划。 |
| policy.mode | manual 仅手动；interval 完成后等待间隔；daily 北京时间每日执行。 |
| policy.interval_minutes | 1～43200 分钟；股票初始 1440，新闻初始 1。新任务默认仅手动，选择固定间隔并保存后才自动运行。 |
| policy.daily_time | HH:MM，初始 18:00，按北京时间解释。 |
| policy.request_retries | 单请求额外重试 0～5 次，初始 2，下次运行生效。 |
| next_due | 下次执行的 Unix 秒时间戳；手动或禁用时为 null。 |
| active | 当前执行或等待恢复的运行信息；无活动执行时为 null。 |
| last_status / error | 最近执行状态及错误摘要。 |

## active / history 字段

| 字段 | 含义 |
| --- | --- |
| run_id / task_id | 本次运行标识与所属采集项目；异常恢复复用运行标识。 |
| started_at / finished_at | 开始 / 结束的 Unix 秒时间戳；界面转为北京时间。 |
| origin / fresh | manual 手动或 schedule 计划；fresh 表示明确从头创建新批次。 |
| baseline_revision | 执行前游标版本，用于判断恢复时是否已推进断点。 |
| status / error | complete、paused、error 等结果及错误摘要；完成表示当前业务数据已发布。 |
| result | 结果摘要，如 snapshot_id、collected、expected_count、pages。 |

活动记录不计入已结束运行的 100 条配额。运行记录不进入业务归档队列，超出配额直接从 Redis 移除，不转存 MySQL。

<!-- topic:归档与错误记录 -->
# 归档与错误记录

运行记录页面分成“采集记录 / 归档记录 / 错误记录”三个标签。后两类由 `collection.records` 插件管理；列表接口按 `project_id` 查询，新记录在前。

## 共同字段

| 字段 | 用途 |
| --- | --- |
| id | 唯一记录 ID，精确删除和去重依据。 |
| project_id | 所属采集项目，例如 sina-stocks；配额按项目独立计算。 |
| created_at | 记录创建时间，界面显示北京时间。 |
| version | 产生该记录时的应用版本。 |

## 归档记录，每项目 100 条

| 字段 | 用途 |
| --- | --- |
| snapshot_id | 关联列表发布批次；不意味着保留历史列表数据。 |
| status | complete 已完成、replayed 已确认重放、superseded 已被新批次替代、invalid 校验失败、failed 归档失败。 |
| started_at / finished_at | 归档尝试的开始和结束时间。 |
| row_count | 本次处理的业务行数；新闻包括新增、重复确认和修订，并非全部为新增加的新闻。 |
| error | 归档结果中的错误摘要。 |

## 错误记录，每项目 300 条

| 字段 | 用途 |
| --- | --- |
| stage / error | 出错阶段与具体原因。 |
| request_url / status_code | 脱敏请求地址和 HTTP 状态；非 HTTP 错误可为空。 |
| metadata | 页码、批次、消息位置等诊断元数据，保存前脱敏。 |
| body | 脱敏后的错误原文样本，每条最多 64 KiB；不是成功响应归档。 |
| body_truncated | 样本是否被截断。 |
| original_bytes | 截断前原始字节数。 |
| original_sha256 | 原始内容的 SHA-256 摘要，用于识别同一大响应而不保留完整正文。 |

**先修复并验证，再清除对应错误记录。** 在错误页选择具体记录，确认问题已经修复并验证，再点击“清除已修复记录”。`clear_errors(project_id, record_ids)` 仅删除明确传入的 ID，不清空项目；操作期间的新错误继续保留。

查看记录或后续采集成功都不会自动清除错误。超过每项目 300 条上限时最旧记录按容量规则淘汰。错误原文、诊断和归档记录始终不写入 MySQL。

<!-- topic:MySQL 当前股票表 -->
# MySQL 当前股票表

股票功能只使用 `stock`，保存最新完整股票列表，不保留历史完整快照。主键 `(source, unified_code)` 保证同一来源的股票身份唯一。

完整列表业务内容相同则跳过 SQL 替换，generation、started_at、updated_at 保留最后实际变更时的值；最新成功核验进度在 Redis stocks:committed:<source>。有业务变更时仍整份事务发布，失败则旧列表完整保留。

| 字段 | 用途 |
| --- | --- |
| source | 数据来源，例如 sina。 |
| node | 来源数据节点，当前 hs_a。 |
| unified_code | 项目统一代码，例 000001.SZ、600519.SH、920000.BJ。 |
| code | 六位字符串代码，保留前导零。 |
| name | 股票名称。 |
| market | SH 上海、SZ 深圳、BJ 北京。 |
| source_symbol | 来源代码，如 sz000001。 |
| generation | 当前列表发布身份，用于重复投递与旧消息校验，不是历史快照表。 |
| started_at | 当前批次开始时间，UTC。 |
| updated_at | 当前列表采集完成时间，UTC；随归档写入，用于展示数据的新鲜度。 |

新列表在 Redis 中完成分页暂存及完整性验证，再在一个 SQL 事务中替换当前列表；失败保持旧列表。MySQL 不保存成功请求原文、采集历史、归档历史、错误原文、分页证据或隔离消息。

应用启动只检查必要结构。新环境可以显式运行 `init-db` 创建缺失的 stock、finance_news、trade_calendar 业务表；已有环境的结构变更需针对性 SQL，不会随应用升级自动执行。

<!-- topic:财经新闻表与增量断点 -->
# 财经新闻表与增量断点

`finance_news` 保存新浪 7×24 全球财经直播的规范化业务内容，按 `(source, news_id)` 去重。不会每天覆盖或删除历史新闻。

| 字段 | 用途 |
| --- | --- |
| source / news_id | 来源与来源新闻 ID，组成主键。当前来源为 sina。 |
| title | 从【标题】提取；无显式标题时取正文开头，最长 256 字符。 |
| content | 去掉 HTML 标签的新闻正文，保留段落；不保留整份 API 原始响应。 |
| published_at | 来源发布时间，由北京时间转为 UTC 存储，界面转回北京时间。 |
| source_updated_at | 来源修订时间，阻止旧响应重放覆盖新内容。 |
| is_important | 来源焦点标志或分类 9 表示重点新闻。 |
| tags | 规范化分类 ID 和名称，JSON 数组。 |
| url | 来源文章地址；无单篇地址时链接至直播页面。 |
| first_seen_at / last_seen_at | 首次写入和最近实际写入版本的观测时间，UTC；相同内容重复采集不刷新。 |

每页独立事务归档，成功后删除对应 Redis 消息；SQL 故障时队列留在内存。归档条数包含重复确认和更新，不等于新增条数。业务字段和来源版本相同或响应更旧时不执行 SQL 写入；仅观测时间变化也跳过。首次只采集第一页，最多 50 条；之后遇到上轮已归档新闻即停止翻页。已停止页之前的历史修订不保证被追溯发现。

新闻 `job_key=sina-news-v1`，项目 ID 为 `sina-news`。断点 `cursor` 字段：

| 字段 | 用途 |
| --- | --- |
| batch_id / started_at | 当前增量运行的标识与开始时间。 |
| phase | fetch 采集、awaiting_archive 等待入库、complete 已确认归档。 |
| before_id | 下一页只请求比该 ID 更早的条目，避免新增新闻造成偏移翻页漏项。 |
| high_watermark | 上次完成运行的最新新闻 ID；当前运行全部归档确认后才推进。 |
| upper_id | 本轮首条新闻 ID，作为新的增量上界。 |
| pages / collected | 已入队页数与处理条数。 |
| covered | 是否已接上上次增量断点。 |

若来源可见窗口已结束仍未接上断点，会保存 coverage 错误并停止，不能宣称无缺口。检查后使用“从头重新采集”可建立新的最新窗口基线；已有新闻不会删除。网页不是无限历史数据接口。

<!-- topic:交易日历表与月份断点 -->
# 交易日历表与月份断点

`trade_calendar` 保存“大 A 交易日期（巨潮资讯）”，包括交易日和休市日。日期缺失表示未采集，不当作休市。

| 字段 | 用途 |
| --- | --- |
| source | 来源，当前为 cninfo。 |
| trade_date | 自然日 DATE，与 source 组成主键，同一天不重复插入。 |
| is_trade | BOOLEAN，来源 isTrade=1 表示交易日，0 表示休市；不以星期自行推断。 |
| updated_at | 最近一次业务内容变更的观测时间，UTC；相同内容不更新。 |

来源最早日期为 1990-12-19。首次补齐至下一自然年 12 月；以后每轮维护本月至下一年 12 月，并补齐历史缺失月份。2026-09 维护 2026-09～2027-12。范围依据北京时间计算；未来安排可能修订，采集值只代表来源当前返回结果。

按完整月份校验后先入 Redis，每 60 秒按月独立事务归档。日期不完整、空列表、重复/跨月、交易标记或星期无效时不覆盖数据，保留失败月以续跑。完全相同日期跳过 SQL 写入，只推进 Redis 观测标记；来源没有修订版本，使用观测时间避免旧响应覆盖新月份。

项目 cninfo-calendar，job_key=cninfo-calendar-v1。`checkpoint` 的 cursor 字段：

| 字段 | 用途 |
| --- | --- |
| batch_id / started_at | 本轮标识与开始时间。 |
| months | 本轮实际请求的月份列表，包含历史缺月及本月至下一年年底。 |
| maintenance_start / end_month | 本轮本月和下一年 12 月；运行中保持固定，下一轮重新计算。 |
| pages | 已入队月数，也是 months 中下一月的索引。 |
| collected / expected_count | 已处理/预计处理的自然日数量，包含休市日。 |
| phase | fetch、awaiting_archive、complete；最后一个月提交后才完成本轮。 |

`archive:progress:cninfo-calendar-v1` 字段沿用新闻归档进度，page 代表本轮月份序号。`archive:observed:calendar.month:cninfo` 保存每月最新成功核验时间，与本轮断点分开。历史补采计划根据 SQL 完整性计算，即使 Redis 重启也跳过已完整的历史月份；未归档数据和执行计划仍会因 Redis 重启而丢失。

没有额外来源参数，执行计划和 cninfo.com.cn 共享频率在采集管理统一设置。新任务默认手动，固定间隔预设 1440 分钟；从头重新采集会核验全部历史，普通采集只补缺及维护。

<!-- topic:连接与容量参数 -->
# 连接与容量参数

参数来自本机 `config/local.toml`，示例为 `config/app.example.toml`；本文不展示实际密码。实际以配置和界面保存值为准。

| 参数 | 含义与默认值 |
| --- | --- |
| app.environment | 环境说明，隔离由 redis.namespace 决定。 |
| redis.host / redis.port | Redis 地址，默认 127.0.0.1 / 6379。 |
| redis.password | Redis 密码，可由 EMPIRE_REDIS_PASSWORD 覆盖。 |
| redis.db / redis.namespace | 逻辑库默认 0；键前缀默认 empire:dev。改前缀相当于使用另一套进度空间。 |
| redis.url | 可选连接 URL，优先于拆分参数，可能包含凭据。 |
| mysql.host / mysql.port | MySQL 地址；示例端口 3307，未配置时默认 3306。 |
| mysql.user / mysql.password | 认证用户及密码；密码可由 EMPIRE_MYSQL_PASSWORD 覆盖。 |
| mysql.database | 业务库名；启动不自动创建或迁移数据库。 |
| mysql.connect_timeout | 连接超时默认 5 秒；读写超时当前固定 20 秒。 |

连接配置修改后重启。Redis 要求 noeviction，当前按用户要求关闭 AOF、自动 RDB 和日志输出；服务或电脑重启将丢失全部内存状态。MySQL 3307 已完成维护，binlog、普通查询、慢查询和错误日志输出关闭，旧日志已清理，见 sql/changes/2026-09-23-low-write.md。InnoDB redo/undo 保留，属于事务恢复所需文件。应用启动不修改服务全局设置。

## ingest 容量保护

| 参数 | 含义 |
| --- | --- |
| high_watermark / low_watermark | 共享 Redis 内存达到高水位暂停、低于低水位恢复；默认 0.70 / 0.50，要求 0 < low < high < 1。 |
| max_queue_entries | 本项目消息队列上限，默认 100000；达到上限暂停，不删除未归档消息。 |
| max_page_bytes | 单次入队消息字节限制，默认 524288，即 512 KiB。 |

完整股票批次在 Redis 中等待校验和发布，项目容量必须能容纳该批次。内存水位反映整个共享 Redis；本机配置可与默认值不同。容量参数重启后生效。

<!-- topic:归档与采集参数 -->
# 归档与采集参数

## archive

| 参数 | 用途 |
| --- | --- |
| interval_seconds | 自动归档周期 60 秒，只处理规范化业务数据，不处理三类运行和错误记录。 |
| batch_size | 单次 Redis 扫描读取条数，默认 100，不是股票总数；完整列表的 SQL 事务不能按此值拆开。 |

启动恢复积压；不完整批次等待后续页面。事务提交前失败保留队列，并写 Redis 归档失败记录，不把有效业务数据复制为错误样本；提交后确认失败允许重放，当前发布身份阻止旧数据覆盖新列表。旧参数 claim_idle_ms、max_batch_bytes 已不再使用。

明确从头重新采集后，可在游标证明新批次已替代旧批次时释放旧不完整临时页，留下 superseded 归档记录；完整有效但尚未成功写入 MySQL 的数据不会被此规则清除。

## sina_universe

`page_size` 为股票接口每页数量，1～80，默认 80。修改后重启；如果与未完成断点不一致，需要明确从头重新采集。

## sina_news

每页固定 50 条，首次只加载第一页；之后接上上轮 ID 就停止翻页。旧 `refresh_pages` 参数已取消。执行频率在采集任务统一设置，最短 1 分钟，共享 HTTP 请求间隔仍由网站频控管理。

## rate_groups.<组名>

| 参数 | 用途 |
| --- | --- |
| domains | 域名后缀列表，如 sina.com.cn 包含根域及所有子域名；修改后重启。 |
| min_interval_ms | 同组请求最小间隔，默认 2000 毫秒；界面保存的 Redis 覆盖值优先。 |
| max_concurrency | 同组并发上限，默认 1，当前为单进程约束；修改后重启。共享许可时间保存在 Redis。 |

分页、重试和重定向都经过共享频控。HTTP 429 触发整组冷却，修改间隔不清除冷却。HTTP 接口默认总等待超时 120 秒、最多 5 次重定向。

执行计划和请求重试次数由采集任务页管理。任务执行间隔是“多久采集一次”，网站请求间隔是“一次采集中请求多快”，两者独立。
