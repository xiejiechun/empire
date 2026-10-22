# P3：回购完整性诊断及必要修复

状态：**已实现、相关专项与真实全源核验通过；完整回归未通过，容量超限阻断正式发布；P3未验收。** 本批不实施P4、回购支出/实际注销计算或新业务表。P2严格002731失败与原B1～B4不结案。生产数据本轮已恢复一致，不等于修复已部署；当前安装包仍为P2，旧包存在再次遗漏证明更新的风险。

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
| 当前累计/区间支出/注销 | 原正式列表/详情语义保留并补帮助；本批不提供O6期间支出、O8实际注销 | P3同包桌面未执行（未生成新包）；P4后续批次 |
| 分红/股息率独立依赖 | 000001仍应0.609/11.44×100=5.3234265734…%；600938、historical_signal及B项不放行 | dependencies-with-redis.json exit0：正常共享Redis可选证据下P1/P2已计算，600938数据阻断、historical_signal来源受限，B4确切ID仍在；同包桌面待完成 |
| 容量 | 旧报告绑定变化，实际重测原50000行/原阈值；最后一次导入86.4695秒>冻结60秒，失败 | capacity-final.json/log exit1，8项输入绑定均匹配；查询、空间预算通过，全50000键内容一致、重复0业务DML、修订1行、六清理true。此前capacity.json为锁拒绝，无测量；capacity-serial.json导入90.0248秒失败。精确前像e204cfb的baseline-control.json同机88.1008秒也失败。两版都超限，具体耗时根因尚未证实，不能归咎特定后台应用或证明本次metadata显著退化。设计卡引用本轮真实失败报告，未改工具、协议、历史基线或阈值 |
| 文档与发布 | 回购数据说明、原SQL表及共享指纹正文已同步、关联保持，review/ruff/mypy通过；正式发布被容量阻断 | 初次统一门禁2a81d1bbcc50472fb16d6ab81b7f990d exit1，第005步拒绝旧容量报告绑定；没有publication.json或P3新包，同包桌面未执行。最终输入的门禁与资源恢复结果见下文 |

正式命令：`.venv/Scripts/python.exe -m empire doctor --project eastmoney-repurchases ...`（exit1，partial原因见上）；`audit_state.py`（exit0，生产只读快照）；`pytest tests/integration/test_repurchase_archive.py tests/test_repurchases.py tests/test_repurchase_verification_tools.py -q --basetemp=build/pytest-p3-related`（EMPIRE_INTEGRATION=1及显式13348配置，exit0）；`scripts/verify_repurchases.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output build/returns-p3-20261022/private-source.json --timeout 240`（exit0）；`production_verify.py`（exit0；脚本纳入原始证据）；`ruff check ...`及`mypy`（exit0）。完整日志、输入hash和运行身份以原JSON为准。

## 剩余限制

源接口无快照令牌，整轮各页代表本轮读取当前版本，不声称同一秒快照或完整历次修订。本轮证明恢复只覆盖当前可见全集与当前修订版analysis；原5553证明精确旧成员不可重建，严格历史信号回放、区间回购支出、实际注销、持仓现金与P4均未实现/受限。P2的002731四个quote证券日严格失败及B1空名债券、B2原46单元、B3旧全历史/未知增发、B4原ID继续保留；600938仍须阻断。回购恢复不等于整个研究主题或全项目所有数据通过。

开发补充：81项回购UI、分红汇总、股息率及文档专项exit0（ui-doc-tests.log）；ruff、严格mypy和文档契约均exit0。baseline-control为修复前源码的容量对照，不是当前版本验收；不使用其报告替代候选报告。读基线资源活动时发现UUID库已被正常清理，诊断返回Unknown database，未删除/重建或重跑来源。

## 完整回归与发布阻断

在实现提交`ca657447338118d6618e1be2bd20fbb7a54ccc68`执行完整回归，期间src/scripts/tests/sql/config与提交无差异。命令为`EMPIRE_INTEGRATION=1 EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json .venv/Scripts/python.exe -m pytest --basetemp=build/pytest-p3-full --junitxml=build/returns-p3-20261022/full-tests.xml -q`。实际退出码1，3311.64秒：4077 passed、2 failed、5 skipped。原始[日志](shareholder-return-p3-development-2026-10-22/full-tests.log)、[JUnit](shareholder-return-p3-development-2026-10-22/full-tests.xml)及[命令身份](shareholder-return-p3-development-2026-10-22/full-tests-exit.json)均保留。

两项失败为`tests/test_market_mapping.py::test_capacity_evidence_is_bound_and_enforced[stale]`与`[over_budget]`，它们首先要求当前全部容量证据有效；回购旧E6f报告不再匹配dataset.py，故在该前提失败，不是它们构造的反例被错误放行。不能将整轮写成通过。五项skip均为`tests.integration.test_state_unit_isolated`要求额外`Explicit isolated drill opt-in required`的既有演练，不记作本轮通过。Ruff、严格mypy、architecture_contract及assembly_contract各自exit0，不能替代失败的完整回归或统一门禁。

生产根因补证[causal-evidence.json](shareholder-return-p3-development-2026-10-22/causal-evidence.json)确认原末批86条的规范内容hash全在可信缓存中，结合已完成checkpoint/清队和旧SQL证明，支持已复现的归档路径缺陷；不从旧5553聚合摘要猜测成员。最终容量[capacity-final.json](shareholder-return-p3-development-2026-10-22/capacity-final.json)为当前实现的真实失败测量，不能只刷新旧报告hash。解决剩余导入预算并重过完整门禁后，才可生成P3包及补做同包桌面；本轮不继续无新线索地反复请求来源或跑容量碰运气。

更新设计卡引用后，`scripts/verify_database_design.py`再次实际exit1，拒绝理由为`repurchases.page 容量预算超限：import_seconds`（current-capacity-gate.log），不是仍以旧绑定替代当前测量。最后一次正文修改后的文档生成、review及verify_documentation均exit0；`pytest tests/test_documentation_build.py tests/test_documentation_review.py tests/test_documentation_contracts.py tests/test_documentation_sources.py tests/test_storage_help.py tests/test_repurchase_ui.py tests/test_distribution_ui.py tests/test_distribution_cache.py tests/test_dividend_distribution.py tests/test_dividend_yield.py -q --basetemp=build/pytest-p3-final-docs`实际120 passed、121.57秒、exit0（final-doc-tests.log）。这一专项通过不覆盖上述完整回归失败。

## 最终门禁、桌面恢复与资源交接

实现提交为`ca657447338118d6618e1be2bd20fbb7a54ccc68`。在后续干净证据提交`8db0dca`冻结Git HEAD及受保护输入，实际再次执行唯一入口`verify-release.ps1`：运行号`1d82d451c39247f6b2f15cc0968b5b4c`，退出码1。环境、依赖、帮助生成检查及文档契约四步通过，第005步按本轮实测报告拒绝`repurchases.page 容量预算超限：import_seconds`。原始[运行日志](shareholder-return-p3-development-2026-10-22/final-release.log)、[命令/提交/退出码](shareholder-return-p3-development-2026-10-22/final-release-exit.json)与[第005步](shareholder-return-p3-development-2026-10-22/release-1d82d451c39247f6b2f15cc0968b5b4c/steps/step-005.json)保留。没有publication.json、没有新包切换，也未执行P3同包桌面验收；没有绕过门禁另行打包。

自有13348在全部开发验证结束后，使用已审阅`stop_owned_mysql.py`重新核实实际UUID、端口、datadir、仅四系统库、无其他客户端，然后正常SQL SHUTDOWN，exit0且端口关闭，见[资源关闭原件](shareholder-return-p3-development-2026-10-22/private-mysql-close.json)。没有强杀数据库、删除锁、重启或清空共享Redis。后续会话不能假定13348仍运行。

恢复的是既有P2包：release `4c672429732f48669159d410a91917d9`，包绑定实现`dba889f8b7aeb086b7d8264971a9b1c2a62d9b3a`，EXE SHA-256 `7daaf84de6a00f36eb745a980ab3d632e07da1c07d0c5dd33531d3231a54f576`。通过computer-use实际重新打开，PID52932、窗口30346504，观察工作台“本地服务已连接”及待归档0，再实际点击数据浏览并观察数据目录正常响应；[窗口原观察](shareholder-return-p3-development-2026-10-22/desktop-restoration.json)仅证明旧包恢复。原正常关闭发生在实采前，未强制结束Empire。

随后`post_release.py 4c672429732f48669159d410a91917d9 restored-p2-package`只读核对exit0：[包与正式查询原件](shareholder-return-p3-development-2026-10-22/restored-p2-package.json)确认EXE/产品树与原P2包一致，两份config、插件偏好、48项SQL保存设置均保持，生产UUID仍为`77f9ba30-b666-11f1-81c5-380525361d4e`，回购审计仍有效、pending0、B4原ID仍在。正式查询复用当前源码的既有query提供者（本批没有修改这些查询），不是在新P3 EXE内执行。旧包按原保存策略恢复日常任务，没有改网络、调度或任务设置。

**下一步明确**：查明并解决原50000行导入预算超限，在不修改冻结工具/协议/基线/阈值的前提下取得新实测；再执行完整相关回归及统一门禁，生成同一P3包并做业务页面、准备检查和正常关开验收。此前P3保持“已实现待完成验证/发布、未验收”。当前数据一致性恢复、程序修复、正式部署三项分别记录；旧包仍可能再次遇到证明更新缺陷。P4及原B项/P2严格002731失败不随本轮改变。
