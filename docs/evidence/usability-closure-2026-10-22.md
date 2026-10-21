# 按用途和范围证明数据可用性：实施、发布与真实桌面结案

本专项已实现并完成适用验收。结果是**按明确用途及证券日期证明局部可用，同时准确保留阻断和来源限制**；不是所有历史数据通过。设计先登记于[算法及U1～U10矩阵](../data-usability-scope.md)，B1～B4原失败仍归[完整性账本](../business-integrity-status.md)。未重复A～F重构，没有删除历史业务数据，没有新增来源旁路、双写或启动迁移。

## 实际实现及唯一入口

| 用户目标 | 根因与实现 | 验收与边界 |
| --- | --- | --- |
| 资本范围语义 | 原严格全集比较不能直接说明某证券用途。现有capital_actions/query.preparation_check接公共PreparationScope，经同一RR/READ ONLY快照读取完整证券单元，校验精确业务键/规范内容/hash/count/digest/契约/观测版本，全部匹配后才按event_date投影。新增preparation.py由原查询调用，未选证券仍走原严格全集检查 | U1～U4通过。证券外未知不误阻断；所选证券内不匹配不能靠日期过滤通过。最多100证券、每单元2000行。只有聚合摘要、没有精确来源成员清单时，无法从历史超集反推来源子集，该证券继续阻断 |
| 预案与实施防双计 | 正式list_events保留全部预案/实施。原理论复权已排除预案、取消并拒绝同日并列；增加同报告期不同除息日多实施歧义拒绝，包括一条在分析区间前的情况 | U5通过防双计回归。不同报告期独立实施仍计算；歧义表示无法裁定关联，不表示确认同一事件。缺稳定事件ID、预案到实施关联和逐修订真实可用日，不按金额相近合并、不删历史。股息率/现金收益未实现 |
| 停复牌盘后证明 | 原10-21覆盖当天、确认13:40，确实早于15:30，原失败正确。另有无变化核查只推进统一摘要、SQL时间保留的情况。confirmed_coverage沿既有查询只读核验精确范围、checked_dates hash、版本、有效索引和观测顺序，最多同月31个精确键，补SQL已有连续范围时间，不延伸日期 | U7～U8通过。真实同包正常流程恢复；摘要缺失/失配/过期/超前/Redis离线回SQL，SQL仍盘前则失败。未刷新SQL、不跳过检查、不把缺日当空日 |
| 正式准备结果 | 公共CheckEvidence新增reason/observed_at；原页面详情展示用途/证券日期、实际证据时间、满足条件、阻断、非阻断限制，区别未检查/检查失败/来源受限/通过。三资本、停复牌和两复权cache_revision=2防旧成功缓存 | U6/U10通过。analysis只授权当前修订版事后研究；historical_signal缺修订可用日仍阻断，不把报告期或最早预案公告日套给修订 |

无旧正式入口退役：升级原preparation_check及calendar_coverage，没有并行准备系统。装配baseline/order不改，仅assembly-feature-changes.json精确声明9个scoped/cache_revision字段及独立测试，唯一门禁显式传入；未解释身份或顺序变化仍拒绝。没有业务表、schema、来源解析、采集语义、消息身份或归档格式变更；55表设计门禁通过，不需要DDL或迁移。

## 真实范围结果与不可外推部分

[可选摘要正式审计](usability-optional-formal-audit-2026-10-22.json)为生产只读，实际时间2026-10-21T16:19:31.189871Z；SQL守卫拒绝DML，不启动采集/归档、无来源请求，前后源码hash一致。9证券×三资本，日期2026-01-01～10-20；另有000001 historical_signal及原45历史键正式查询。单范围一致快照和跨范围分时读取分别记录，不冒充全库原子快照。

| 实际输入 | 结果 | 证据与限制 |
| --- | --- | --- |
| 000001，三资本，analysis | 数据条件均满足；事后分析非阻断限制 | 匹配摘要10-21T05:40:05.472355Z，配股.479414；完整键/内容证明后日期投影。其他证券未知不阻断 |
| 600000同范围 | 分红、增发满足；配股失败 | 每项criterion、findings、精确摘要见JSON，不用两项通过覆盖第三项 |
| 600938、000528、301232、000403、000498、002475分红 | 继续检查失败 | 原预案与当前实施保留；完整单元不匹配，不能从聚合hash猜日期内当前成员 |
| 001228增发，含1043980未知详情 | 继续失败、详情未知 | 未删原记录，未推断过去曾取得详情或补零 |
| 000001同范围historical_signal | 其他数据条件满足，唯temporal来源受限且阻断 | 缺事件关联和逐修订真实可用日，不能借事后分析通过 |
| 未选证券的原严格范围 | 分红、增发仍失败；配股当次通过 | 原全集结论保留，新局部成功不冲销原失败 |

早期[只SQL审计](usability-formal-audit-2026-10-21.json)中10-16证据超三日的失败保留。后续显式连接既有可选Redis能力取得匹配摘要，不能改写为第一次已通过，不算新实采。原29分红/16增发共45键逐键可查；本次容量当前源外30键属于不同时间快照，原29不改。

## 停复牌：调度、真实恢复与时间边界

保存策略enabled=true、interval_seconds=43200、use_proxy=true、proxy_fallback=true、daily_time=18:00保持。当前采用12小时间隔，不保证恰在收盘后执行；不能把18:00字段误说成已启用每日18:00调度。需要当日盘后证据时走正常立即采集，或由用户选择每日策略保存；本次未改日常计划。

同包`D:/project/empire/dist/Empire/Empire.exe collect-suspensions`从`C:/Windows`使用程序目录config，无fresh，回查最后覆盖日。按完整来源日期响应，不按股票采集，随机30股票门槛不适用；未修改解析/采集语义，不宣称新30股票严格验收。三轮为本次有界时效诊断，未固化日常重复下载。

| 原始回执 | 实际结果/退出码 | 业务与时效 |
| --- | --- | --- |
| [before](usability-suspension-before-2026-10-22.json) | 只读快照exit0；coverage/freshness实际fail | 连续覆盖至10-21，确认05:40:10Z=北京时间13:40:10，早于15:30 |
| [首次CLI](usability-normal-suspension-1-exit-2026-10-22.json)、[异常原文](usability-normal-suspension-1-exception-2026-10-22.txt)、[after1](usability-suspension-after1-2026-10-22.json) | **CLI实际exit1**，不能当成功命令 | PowerShell直接启动GUI EXE重定向，父进程异步退出后输出句柄无效；finalprint line334 OSError22，stderr349再失败。业务完成21～22两代理/pending0，异常窗口正常Close、无强杀。这是启动方式限制，不以业务成功掩盖进程失败 |
| [第二轮CLI](usability-normal-suspension-2-exit-2026-10-22.json)、[after2](usability-suspension-after2-2026-10-22.json) | 实际exit0，1代理/直连0/回退0，pending0 | subprocess.run持有communicate管道，无timeout强杀；22→22完整空响应，建立同日精确键，SQL确认17:09:08.609606Z |
| [第三轮CLI](usability-normal-suspension-3-exit-2026-10-22.json)、[after3](usability-suspension-after3-2026-10-22.json) | 实际exit0，1代理/直连0/回退0，pending0，六check均pass | 同日完整空响应热重复，整个SQLstate与第二轮相同；可信摘要真实推进17:09:40.538832Z，不刷新SQL |

恢复只证明**最近已结束交易日2026-10-21 15:30**；当时为10-22凌晨，不能说已取得10-22收盘后证据。原B4错误ID仍在；当前603517两日查询成功无法恢复出错当轮差异，不结案、不清该ID，不合并不同复牌时间/说明/原因。

## 开发、容量与正式发布

| 验证 | 原命令及实际结果 | 证据 |
| --- | --- | --- |
| 领域U1～U8 | 8文件pytest exit0，153 passed；范围外未知、范围内缺行/字段、同数异键/同键异内容、有效空范围、预案实施歧义、未来信息拒绝、盘前盘后及Redis降级 | [完整命令/退出码/JUnit摘要](usability-development-2026-10-21.json) |
| 隔离全链路/公共恢复 | EMPIRE_INTEGRATION=1，自有13348，四文件pytest exit0，72 passed；UUID库/Redis namespace，来源→规范→入队→统一归档→SQL；重复免DML、冷热摘要、迟到旧版、提交后重放、成功清队、失败保留且不推进 | 同上；test_capital_archive、test_suspension_archive、test_adjustment_pipeline、test_issue_availability_archive |
| 真实容量绑定 | 冻结第二轮exit0；5580证券/636期/58614来源行/SQL56168行，638代理、直连/回退0、pending0；10次查询max2.6677ms，六清理true | [新真实报告](usability-dividend-capacity-2026-10-21.json)。首轮期间测试改变被final_source_identity拒绝，原失败保留，不刷新旧hash |
| 首发失败 | verify-release.ps1 exit1，4001pass/4fail/5原opt-in skip，未切换包；test_release_steps精确命令漏--feature-changes，补原断言参数一行，13文件回归187pass | [失败回执](usability-release-attempt1-2026-10-22.json)，失败JUnit在build保留 |
| 唯一成功发布 | verify-release.ps1 exit0，release a62017f2868244ffb86e4bf2c7dd7f02；4005pass/5原opt-in skip/20warnings，2803.56秒；静态、strict13类型、143说明、55表设计、架构、精确装配、隔离容量quick、四档离屏、PyInstaller及搬移通过 | [2019输入/58输出/25步骤审计](usability-release-audit-2026-10-22.json)；step23首次缺配置exit1为预期，其余0 |

冻结release_lock、性能工具/协议/历史基线/阈值未改；不把旧T3或离屏布局说成新的真实性能/桌面验收。5项既有显式opt-in跳过不算通过。A～F身份、顺序和原验收保持。

包绑定干净提交`dd86f9c07e886ac4dffad1bcd09d94b83d5086a3`，主要实现`969686e666fb04463ed48df86ebddb6eb936fc4c`。source SHA256 `7127c658b6b8285e35656a742e1afbcfe2988efa186ab6dbc40ac9d978d29466`；EXE `9a89eee2b4da1b2be09346d251272e6f3c16269fe295931100a847fbf6cedc43`；安装树`665922aa1cb11850a326dd1b1e24dbb3757122b719d8146f5ac11ba11de60cb5`。在结案docs/HEAD修改前审计2019受保护输入一致，现有正确快捷方式保留、目标/cwd/hash实际核实。

## 同包真实桌面及资源

使用computer-use技能（本机`C:/Users/52948/.codex/plugins/cache/openai-bundled/computer-use/26.1013.40934/skills/computer-use/SKILL.md`）的@oai/sky操作真实窗口；[原观察文本及截图ID](usability-desktop-observations-2026-10-22.json)逐次记录，截图在工具会话实际显示，未伪造/重绘。窗口51186346检查后Alt+F4正常退出，list_windows及进程均无Empire，正式路径launch_app重开唯一窗口18550394，工作台保持可见。

| 可见动作 | 实际结果 |
| --- | --- |
| 原数据准备入口 | 初始未检查，不自动全历史扫描；改范围提示尚未重新检查 |
| 长期价值研究→股东回报/稀释，000001，2026-01-01～10-20 | 分红详情“通过”，证据05:40:05.472355Z，六条件满足、0阻断、1限制；三资本可用（有限制）。整个研究有回购阻断，不宣称全就绪 |
| 同范围600938分红 | “检查失败”，完整单元未证实1个，字段/键/覆盖/质量/时效仍阻断；日期筛选未掩盖差异 |
| 策略回测→量价策略，000001同日期，搜索分红 | “来源受限”，数据条件满足，只有日期用途条件阻断；明确缺稳定事件关联和逐次修改可用日，当前修改版不用于历史信号；其他研究缺口保留 |
| 说明文档→数据准备 | 范围算法、四状态、实际证据时间、资本历史限制、停复牌15:30及Redis降级新原文随包部署可读 |
| 系统设置→运行状态、正常重开 | 可见Empire 0.1.0 · dd86f9c07e88 · 干净提交，服务连接、待归档0；重开工作台可见，5旧失败任务保留 |

[安装CLI](usability-installed-cli-audit-2026-10-22.json)从C:/Windows默认程序目录config，doctor exit0/真实Redis和MySQL连接；原B4项目doctor exit2 partial，未改全pass。[最终只读核对](usability-post-release-final-2026-10-22.json)命令exit0：两config、插件偏好字节及48保存设置digest保持；EXE/安装树与journal一致；生产3307 UUID`77f9ba30-b666-11f1-81c5-380525361d4e`未变，固定正式查询可用、原ID保留、global pending0。共享Redis未清未重启，没有删业务数据/锁或改用户网络配置。

[私有13348正常关闭](usability-private-mysql-close-2026-10-22.json)命令exit0，核实际UUID`a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、datadir、四系统库/无其他客户端后SQL SHUTDOWN，端口关闭、目录保留。未强杀数据库或Empire。生产和正常日常计划继续运行，其后新增数据不算本轮严格样本。

辅助失败也保留：审计首次假定journal.shortcut非空而TypeError，实际None表示保留正确旧link，[原log](usability-release-audit-2026-10-22.log)与[修正后实际exit0](usability-release-audit-2-2026-10-22.log)分开；build/post_release.py首次py_compile因finally缩进SyntaxError/exit1，仅修正build脚本后最终核对exit0；导出首轮误假设三资本全集均失败而AssertionError（build/usability-20261021/export-closure.log保留），按实际仅分红/增发失败修正后导出exit0，配股通过原样保留。均未修改产品/门禁迎合辅助工具。

## 剩余限制及交付边界

- B1两空名债券仍缺原块名称或可验证唯一关联。B2原46仍需原证券日期38个1017成功响应及8委托单元缺10分钟键；未再请求、未换样或日期，原严格失败不改。
- B3分红/增发全历史证明仍失败。局部成功不消除29/16历史差异；缺源成员清单时，不匹配证券选更窄日期也不能证明。001228原未知仍需来源提供详情，历史记录保留。
- 历史信号缺逐修订可用日和事件关联，继续来源受限；analysis只指当前修改版事后分析。不承诺股息率、现金收益、历史全市场池或回测引擎已实现；预案/实施歧义拒绝，不猜关联。
- B4原ID`38622b7215a44fe4a5224031bdf4d963`缺当轮差异，当前成功不证明旧冲突修复，未结案未清；新诊断原验收保留。停复牌仅恢复10-21已结束日，以后仍需真实有效确认。

U1～U10适用行为均已验收，外部受限范围保持失败或受限。新表/迁移、采集解析修改不适用；公共恢复约束经领域、隔离及正式全量覆盖。结案只改账本/脱敏证据，不改包内资源、不重打包；包内提交与随后纯证据HEAD分别记录。[实际副本hash和原失败复算](usability-receipt-index-2026-10-22.json)由读取原证据生成；最终文档审阅、契约、设计、相关回归的逐命令退出码存于同目录`usability-closure-checks-2026-10-22.json`，不以叙述替代执行。首轮结案检查因本机技能绝对链接及尚未生成的检查报告链接被正式文档门禁拒绝，[实际失败回执](usability-closure-attempt1-2026-10-22.json)保留；改为可搬移的正文说明后完整重验，不放宽门禁。远程精确核实以实际Git回执及最终交付HEAD为准，不能把包内dd86f9c说成后续证据提交。
