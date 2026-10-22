# P3 发布续接与验收

当前：容量前置阻断已用正式新测量解除；新增事务反例与相关回归27项全部通过，尚未发布、尚未进行P3同包桌面验收。P4不在本批。

原实现、生产恢复、历史失配及全部失败原件见[P3原账本](shareholder-return-p3-2026-10-22.md)。这里续接正式发布，不重新实采或改写原失败。

## 当前现场与身份

从干净main `867ab23adcd6ab72bc3ef02fc97da5bc89ac8a7b` 开始；远程经系统已配置的本机代理只读核实同值，第一次直连GitHub连接失败也记录。未部署产品修复为`ca657447338118d6618e1be2bd20fbb7a54ccc68`。本轮不再修改产品实现、容量工具、协议、阈值、历史基线、表结构、采集解析或日常策略。

12:45只读一致SQL快照为5588方案，摘要`356f1c29cdcc6eac17718be43fdd070cbf6d351021954795f5e0e0be00ac024f`；逐行规范hash、正式audit及coverage一致，Redis前后checkpoint稳定、待归档0、48项保存设置。SQL与Redis分别读取，不声称跨服务原子。原5586历史键保留情况及五项修订沿用原本轮全源证据，不把5588硬编码成永久预期。

现有P2包仍为release `4c672429732f48669159d410a91917d9`、EXE SHA256 `7daaf84de6a00f36eb745a980ab3d632e07da1c07d0c5dd33531d3231a54f576`；通过computer-use正常Alt+F4关闭PID52932后开始独占测量。自有MySQL13348重新正常启动，实际UUID`a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir、仅四系统库及无其他客户端核实；新进程PID36896。生产3307、共享Redis及其他项目进程均未停止/清理。

## 两项回归失败逐项处理

| 原测试 | 原失败断言及分类 | 处理与本轮验收 |
| --- | --- | --- |
| `test_capacity_evidence_is_bound_and_enforced[stale]` | `verify(tmp_path)['tables'] == 55`前置验证拒绝回购旧E6f证据的dataset.py绑定；尚未进入其刻意修改开盘啦源码的反例。过期证据，不是该反例被放行 | 不改测试或断言；用原工具对当前实现实测，设计卡改指真实新报告；结果见相关回归原件 |
| 同测试`[over_budget]` | 同一前置绑定错误；之后设计卡改指真实失败报告时又实际拒绝import_seconds超限；尚未进入其人为超限反例 | 同上；旧失败报告完整保留，不只刷新hash，不调整限额 |

当前有效报告：[paired-current.json](shareholder-return-p3-release-2026-10-22/paired-current.json)。8项bindings、DDL范围及source proof绑定均由原工具生成；来源证明仍为当前产品源码`70c3eb19dbdc22532b357ab7a601bbf6bd4bab4791d28dae91278631eef1c13f`，本轮仅新增测试/证据，无需无新线索重复请求来源。

## 60秒边界及有界对照

冻结`measure_repurchases.measure`在`tracemalloc.start()`之后开始计时，覆盖一次50000行首次导入及事务提交：100组×500的合成样本生成、validate、排序、正式writer旧行查询、规范摘要、驱动转义、批量INSERT。重复导入、单行修订、查询测量、50000完整集合复核均在此计时之外，仍必须执行。不将工具名的import误读为Python模块导入时间。

本轮先执行一次诊断，再预先限定当前/精确前像各一次无profiler测量。两版相同来源首条样本逐字段完全相等，原8项工具/查询/contract绑定除产品dataset外完全相同；同一解释器/锁定依赖/SQL实例与配置，独占Empire实例锁、UUID数据库及Redis前缀，每轮完整清理后再执行下一轮。没有并行写入或结束他人进程，没有更改电源/安全软件。

诊断[profile-diagnostic.json](shareholder-return-p3-release-2026-10-22/profile-diagnostic.json) exit1，不能当容量验收。cProfile包裹未改动的原measure；总179.66秒、进程CPU166.66秒。完整profile的三次load累计95.29秒，write71.71秒、驱动字符串translate29.11秒、SQL归属守卫约4.03秒；后置verify_complete74.84秒在60秒边界外。该聚合profile不把三次load合并值冒充首次导入细分。原工具在profiler下首次67.865秒，超限原样保留。

环境原观测为总CPU31/14/16/18%、可用内存约77GB、磁盘队列0；本轮进程Normal priority、全32逻辑处理器亲和性、QoS无显式节流，原始[环境](shareholder-return-p3-release-2026-10-22/profile-environment.json)及[QoS](shareholder-return-p3-release-2026-10-22/qos-environment.json)保留。RouterProxy等其他任务仍存在，未终止或跨会话发消息。这些有限快照不能证明历史时段具体哪个进程导致变慢。

| 固定实验 | import_seconds / 冻结60秒 | 其他结果与退出 |
| --- | --- | --- |
| 当前实现，原正式入口 | **39.8835257，通过** | coverage最大801.212ms；全部原预算通过，50000逐键内容一致、重复业务DML0、修订1行、空间159678464bytes、六清理true；exit0 |
| 精确前像e204cfb，原API/原阈值/同seed | 39.9122110，通过该导入项 | coverage最大1168.751ms>1000，**整体exit1**，其余原规则保留、六清理true；不能作为当前验收报告 |

当前原命令：`.venv/Scripts/python.exe scripts/measure_repurchases.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --source-proof build/returns-p3-20261022/private-source.json --output build/returns-p3-release-20261022/paired-current.json --timeout 900`，exit0。前像通过[诊断控制脚本](shareholder-return-p3-release-2026-10-22/paired_control.py)调用精确git archive内原measure，未改被测实现；首次报告路径在前像root外，被原路径守卫拒绝，无测量/资源创建；修正为前像自己的build目录后才执行这一次对照。两个日志均保留，不隐去脚本前提错误。

原86.4695秒和88.1008秒失败没有阶段CPU/SQL计时，无法事后精确重建历史慢测的环境根因；本轮不归咎特定后台软件、不声称已修复未知性能缺陷。当前测量在正常重开自有SQL、无本任务并发写入的明确条件下实际满足全部预算，按真实新报告更新当前证据，**并非以前像也慢为豁免**。未反复重跑挑通过样本，前像coverage失败也不复测。历史性能波动仍是限制；统一门禁仍须独立完整通过。

## 补强反例与发布前状态

新增参数化隔离集成覆盖601方案前页修订、末页所有方案可信命中，实际writer末批rows为空且只有coverage需SQL确认：在save_state已执行但事务返回前注入异常，验证旧证明保持、当前集合准备失败、消息保留、checkpoint未完成；恢复后不重新下载即重放提交新证明并清队。另在证明已提交后阻断ACK，验证SQL证明有效但待归档消息保留、任务不虚报完成；恢复后可信重放清队。故障仅在UUID测试库/前缀注入，不污染生产。

原同数异键、同键异内容、未完成轮次、迟到旧版本、重复无DML、历史保留及下载/归档独立测试全部保留。没有删除旧测试或放宽断言。命令`EMPIRE_INTEGRATION=1 EMPIRE_TEST_MYSQL_SETTINGS=<已核实13348文件> .venv/Scripts/python.exe -X utf8 -m pytest tests/integration/test_repurchase_archive.py tests/test_repurchases.py tests/test_repurchase_verification_tools.py tests/test_market_mapping.py -q --basetemp=build/pytest-p3-release-related --junitxml=build/returns-p3-release-20261022/related-tests.xml`，exit0、27 passed、84.63秒。两原失败参数和两新增故障参数均实际执行，见[原始日志](shareholder-return-p3-release-2026-10-22/related-tests.log)及[JUnit](shareholder-return-p3-release-2026-10-22/related-tests.xml)。`scripts/verify_database_design.py`实际exit0、55表/49数据集/12JSON字段。正式门禁仍待执行。

生产数据核验、代码完成、正式发布、桌面验收分别记载。原B1～B4、600938、historical_signal、P2严格002731四证券日、旧5553证明成员无法恢复及回购累计/实际注销限制全部保持。P4、区间回购支出、实际注销和稀释汇总仍未实施。

最后一次测试实现修改后显式documentation_build generate、documentation_contract review及verify_documentation均exit0；逐项审阅原回购/公共摘要正文、页面关联、累计/注销和历史信号限制，本轮无需修改已同步的产品帮助正文。`pytest tests/test_documentation_build.py tests/test_documentation_review.py tests/test_documentation_contracts.py tests/test_documentation_sources.py tests/test_storage_help.py -q --basetemp=build/pytest-p3-release-docs`实际63 passed、62.30秒、exit0；文档契约419文档/3041链接/55表，Ruff相关文件及git diff --check均exit0。正式发布将在此状态冻结提交；最终发布和桌面事实另行续记。
