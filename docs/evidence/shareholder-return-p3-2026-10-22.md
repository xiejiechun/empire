# P3：回购完整性诊断及必要修复

状态：**已实现、相关开发与真实全源核验通过；正式发布及同包桌面待完成；容量导入项当前失败。** 本批不实施P4、回购支出/实际注销计算或新业务表。P2严格002731失败与原B1～B4不结案。

## 现场与根因

从干净main `e204cfb07ecb7d1428c431c033aeba3930be0f82`开始，远程同值；原P2包继续有效。10:10只读doctor：回购无活动任务、无错误，next_due为当日18:00，checkpoint revision312、昨天18:00完成5586方案/23消息/12次代理；全局待归档0。doctor exit1表示运行内隔离无法由CLI确认，其他已取得部分保留，不冒称完整进程快照。正常关闭Empire后才运行生产collector，未启动第二调度器或同时运行第二归档器。

10:13一致只读SQL快照（REPEATABLE-READ、START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY）：生产UUID `77f9ba30-b666-11f1-81c5-380525361d4e`；5586条逐行规范内容hash全匹配，滚动摘要 `1322bf7908bae464addeac6939f3f9b0db7fe6bb7c85fced2caa43324794688d`，与已完成正式checkpoint一致。SQL coverage仍为5553、`6a7832dede22b8ac4cb646ba424d49b6cd177634f28b593dcad4980faf742467`、UTC10-16 01:47:09.508899；SQL进度仅到昨日第13批，Redis已确认23批并清队。前后checkpoint相同。指纹有效5581，另5键无可信缓存（16077/16308/16456/16513/16669；来源日期晚于昨日观测，不能当可信命中），均按正常SQL规则处理；不是丢业务数据。

**程序缺陷已复现**：旧fingerprint只声明方案；前页修订后，末页所有方案都命中可信摘要，归档器免SQL成功清队，dataset.archive_state因此没有机会更新完整集合coverage。601方案隔离反例红测exit1，首键内容已修订、末页全热、任务complete，而SQL仍保留旧摘要。这说明生产现场的证明更新路径缺陷，不将旧count差33解释成33个多余记录或漏采。旧5553证明没有成员列表，无法恢复其精确成员/修订历史；本轮不从聚合摘要倒推成员，不把这一历史限制抹去。

## 实现及正式路径

唯一改动在features/repurchases/dataset：末批在原eastmoney_repurchase_v1/eastmoney指纹桶声明一个非数字coverage项，规范内容为contract/count/digest，观测版本遵守原ArchiveVersion；数字plan_id不会碰撞。集合改变时，原统一归档器将coverage未命中项送入原SQL writer并与collection_state同事务确认；末页方案全部热命中仍可更新证明。全部方案及集合证明重复命中仍免SQL。旧响应不推进新coverage。

旧的“只等末批某个业务行cache miss才写证明”依赖已退役；没有新增兼容转发、队列、来源请求、SQL业务列、表、schema、调度或长期原文存储。原消息payload和登记身份不变，既有缓存缺少该项自然回SQL，不是启动历史格式迁移。无数据表改造，业务数据库DDL设计/迁移不适用。准备查询标准保持：全SQL精确键和规范内容必须匹配源证明；没有按证券空集放宽，也未手改摘要/时间戳。

调用方仍为既有DatasetContribution→统一fingerprint_plan/subset→CollectionState.writer→archive_state；正式query.audit、list_plans/detail和preparation_check保持。SQL/Redis/公共恢复规则不另造实现。

## 当前精确来源差异与准备结果

独立实例开发核验：私有MySQL13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，UUID库和Redis前缀/SQL守卫/资源所有权，完整5588方案、2964证券、12次全代理、直连0、最终pending0，六项资源清理通过。回购按全市场REPURCODE游标请求，随机30股票不适用；全源集合比只抽股票更适合此接口。工具报告的non_stock_scope.reason沿用旧“纯组织迁移”文案，本批实际为证明归档修复，不据该旧标签声称无行为变化；实际请求和集合证据为本轮运行。

生产修复需让新集合证明通过真实原归档路径生效，另执行**一次有界生产整轮**（240秒超时、共享下载器/代理/频控、原collector、原入队/归档；无调度器，不保存日常策略）。隔离实采与生产恢复分开，不固化为日常双读。生产也为5588方案、12次全代理/直连0；精确来源→规范化→Redis消息→SQL全集及正式分页/详情一致。原有5586键全部保留，无来源外历史键；不是通过删历史获得相等。

| 与生产前像比较 | 精确结果 |
| --- | --- |
| 来源新增键 | 16693、16696 |
| 同键内容修订 | 10112（objective）；15721（日期、状态、累计股数/金额）；15892/16118/16179（计划价格/股数上下限）；完整逐字段before/source在原JSON |
| 前像独有键 / 恢复后独有键 / 来源缺失键 | 均空 |
| 恢复后同键异内容 | 空；5588逐行hash有效 |
| 新完整摘要 | 356f1c29cdcc6eac17718be43fdd070cbf6d351021954795f5e0e0be00ac024f |
| SQL真实证明时间 | UTC2026-10-22 02:24:20.728003（北京时间10:24:20.728003） |
| 000001.SZ不限日期及2026-01-01～10-20 | 均空；本轮完整源集合不含该证券，足以解释当前来源可见范围无方案，不证明源外已删除历史或过去各时点无回购 |
| 正式准备 | fields/keys/coverage/quality/freshness通过；temporal为非阻断限制（analysis），historical_signal仍阻断 |

本轮生产写入仅正式回购归档和collection_state共9个SQL写语句，无DELETE/DDL/设置修改；未按查看/成功采集清理任何旧错误（回购原错误0）。B4确切旧ID及并发其他项目错误保持。

## 验收矩阵与执行账

证据路径前缀为`shareholder-return-p3-development-2026-10-22/`（完成归档后可点击，以下文件名与build原件一致）。源代码/工具/配置身份、命令、exit记录分层保留，不手填passed。

| 项目 | 本批执行与结果 | 证据/限制 |
| --- | --- | --- |
| 同数异键 | 隔离SQL变换1→2后准备失败；原历史2保留，来源重采1仍不能冒称全集通过 | test_failed_sql_retains_queue_and_same_count_different_collection |
| 同键异内容 | 改规范内容并同步行hash，数量仍601、invalid=0，全集摘要不符仍失败 | test_incomplete_refresh_and_same_key_content_mismatch_do_not_pass |
| 未完成核验 | 尾页失败不推进fetch断点、不发布新完整证明；前页已归档不能冒称整轮完整 | 同上；601反例 |
| 前页修订、尾页热命中 | 红测确切失败→修复后新完整摘要归档，601键保留、准备通过、清队0 | red-test.log exit1；related-test.log exit0，16 passed |
| 重复/旧版本/重放/SQL故障 | 可信重复免SQL、冷重复0业务DML、迟到旧响应不覆盖、提交后ACK失败重放清队、SQL失败保留、下载不逐批等归档 | tests/integration/test_repurchase_archive.py原恢复专项均保留通过 |
| 真实集合/空查询解释 | 私有与生产全源分别通过；精确键与规范内容比较，历史原键全部保留 | private-source.json / production-source.json，均exit0；各12代理、pending0 |
| SQL fallback | 不启动Redis/ingest的查询用SQL新完整证明；Redis无可用辅助时不改证明 | dependencies-with-redis.json exit0；SQL证明有效。dependencies.json初次脚本exit1：错误地期待陈旧资本SQL单独通过，已保留；它正确阻断未刷时间，不是产品回归 |
| 当前累计/区间支出/注销 | 原正式列表/详情语义保留并补帮助；本批不提供O6期间支出、O8实际注销 | 真实桌面待验；P4后续批次 |
| 分红/股息率独立依赖 | 000001仍应0.609/11.44×100=5.3234265734…%；600938、historical_signal及B项不放行 | dependencies-with-redis.json exit0：正常共享Redis可选证据下P1/P2已计算，600938数据阻断、historical_signal来源受限，B4确切ID仍在；同包桌面待完成 |
| 容量 | 旧报告绑定变化，实际重测原50000行/原阈值；首次因单实例锁拒绝exit1，无测量，保留 | capacity.json exit1（锁拒绝）；capacity-serial.json exit1（真实导入90.0248秒>60，其余原阈值全部通过、全50000键内容一致、重复0业务DML、修订1行、六清理true）。原e204cfb精确源码git archive使用未改原measure函数/协议同机对照baseline-control.json exit1：88.1008秒>60。两版都失败，不能证明本次metadata导致性能退化；并发RouterProxy/Trae负载观测见environment-load.json，但环境耗时根因尚未证实，不把负载解释冒充通过。没有修改工具/协议/阈值；本项仍失败 |
| 文档与发布 | 回购数据说明、原SQL表及共享指纹正文已同步、关联保持，review/ruff/mypy通过 | 最终完整门禁、同包桌面及push待执行 |

正式命令：`.venv/Scripts/python.exe -m empire doctor --project eastmoney-repurchases ...`（exit1，partial原因见上）；`audit_state.py`（exit0，生产只读快照）；`pytest tests/integration/test_repurchase_archive.py tests/test_repurchases.py tests/test_repurchase_verification_tools.py -q --basetemp=build/pytest-p3-related`（EMPIRE_INTEGRATION=1及显式13348配置，exit0）；`scripts/verify_repurchases.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output build/returns-p3-20261022/private-source.json --timeout 240`（exit0）；`production_verify.py`（exit0；脚本纳入原始证据）；`ruff check ...`及`mypy`（exit0）。完整日志、输入hash和运行身份以原JSON为准。

## 剩余限制

源接口无快照令牌，整轮各页代表本轮读取当前版本，不声称同一秒快照或完整历次修订。本轮证明恢复只覆盖当前可见全集与当前修订版analysis；原5553证明精确旧成员不可重建，严格历史信号回放、区间回购支出、实际注销、持仓现金与P4均未实现/受限。P2的002731四个quote证券日严格失败及B1空名债券、B2原46单元、B3旧全历史/未知增发、B4原ID继续保留；600938仍须阻断。回购恢复不等于整个研究主题或全项目所有数据通过。

开发补充：81项回购UI、分红汇总、股息率及文档专项exit0（ui-doc-tests.log）；ruff、严格mypy和文档契约均exit0。baseline-control为修复前源码的容量对照，不是当前版本验收；不使用其报告替代候选报告。读基线资源活动时发现UUID库已被正常清理，诊断返回Unknown database，未删除/重建或重跑来源。
