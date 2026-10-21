# 股东回报与稀释：首批P0＋P1执行账本

2026-10-22，**P0＋P1已实现、开发通过、正式发布及同包真实桌面已验收**。仅实施[已批准方案](../shareholder-return-analysis-plan.md)P0＋P1；P2～P4、股息率、持仓到账现金/现金收益、回购支出汇总和稀释计算未实现。原主题仍检查四资本，回购失败仍阻断主题。A～F已验收状态保持，B1～B4及回购历史失败不冲销。发布绑定实现提交`e6374eaceaba46dcc17e5b8873f37d7a551d9ed3`；本账本及桌面原证据作为后续纯证据提交，不冒称重新构建产品。

## 现场和实现

起点main/远程`db21f1d7d3be439fe495b57d8bbb8a1f85c2b75f`，开工工作区干净；现有修改均为本批。生产MySQL3307 UUID `77f9ba30-b666-11f1-81c5-380525361d4e`。旧release `a62017f2868244ffb86e4bf2c7dd7f02`，EXE SHA256 `9a89eee2b4da1b2be09346d251272e6f3c16269fe295931100a847fbf6cedc43`。复核时48份保存设置，待归档0；未修改配置、偏好、网络/任务/调度。后续状态仍按实际采集变动核实。

`dividends.query.distribution_summary`复用同一REPEATABLE READ只读快照内的证券身份、完整单元键/内容/SQL证明；Redis仅按既有可信摘要补充实际证据时间，缺失/不可用回SQL，不刷新证明。完整证明后再按闭区间除息日筛选。结果包含证券、用途、范围、实际证据时间与检查时间、完整单元摘要、逐笔键、含税金额和限制。Decimal精度60，逐笔不提前舍入；每10股为最终每股值×10。缺证明/身份/必需金额/日期/事件资格或歧义阻断，不填零。

原复权`contract.actions`的事件资格/歧义及数值错误规则迁入唯一公开`capital_actions.event_rules`，复权contract/inputs/query及测试调用方同步迁移；原入口退役，无转发层。默认复权首日归一为左开右闭，分红汇总显式闭区间、不依赖送转分项（名义当期股口径），两者边界分别验证。完整历史记录和预案保留；不按金额/报告期相似合并经济事件。

现有准备报告/详情增加具体产物；已有检查请求自动计算名义派息，报告缓存绑定新契约版本，范围改变独立身份、重新检查重算。原主题检查保持。分红页增加“名义派息汇总”，使用原证券/日期框，变化立即撤销旧结果；不依赖列表分页、状态筛选、价格或回购。未指定范围为未检查；计算结果分别显示已计算、数据阻断、来源受限，其余本批未实现产物明确显示功能未实现。

无采集/解析、来源协议、业务身份/表或DDL变更；不启动迁移，无新增并行准备、计算存储、下载或归档路径。不适用随机30股实采准入；本批只读生产查询不能冒充实采通过。因资本源码绑定变化，另按现行冻结工具实际重测完整分红容量；不更改历史报告或预算。

## 本批验收矩阵

| 方案ID | 批次及理由 | 本批实际验证 / 当前结论 |
| --- | --- | --- |
| S1 | 本批执行：P1主案例 | 生产只读重新核实两键和0.36/0.249，独立算式360/1000+249/1000=609/1000元/股、6.09元/10股；正式桌面准备详情及分红汇总均一致，已验收 |
| S2 | 本批执行独立性；O3数值及补价格属后续P2 | 生产复权仍因无归档日行情阻断；同输入名义派息已计算；股息率/持仓现金明确未实现，未加价格采集 |
| S3 | 后续批次P2 | 股息率尚无计算，禁止用理论复权/原始记录代替，未执行补价或股息率数值验收 |
| S4 | 本批执行 | 正式查询及桌面四边界均为0/0.36/0.36/0.609；600000独立结果0.42；日期或证券改变立即未检查，回000001重算0.609。准备重新检查时间03:32:43→03:34:00，未刷新来源证据时间，已验收 |
| S5 | 本批执行 | 正式600938及同包桌面仍数据阻断；生产历史只读保留。开发预案+实施只计实施且输入不变；其他原失败记录不清理 |
| S6 | 本批执行 | 合成同日并列、跨范围同报告期不同除息日、未知日期/金额、重复键、状态/税口径未知均拒绝；不同报告期独立两笔可算 |
| S7 | 本批执行 | 私有SQL同数异键、同键异内容、缺记录和缺proof在日期投影为空时仍阻断；完整证明空范围为0；范围外未知证券已有精确单元回归 |
| S8 | 本批执行P1时间/缓存；逐修订版本建设后续 | 正式historical_signal来源受限；私有SQL/已有可选摘要失配、过期、超前、离线反例；缓存读不重算/不延TTL，force及证券/日期变化重算 |
| S9 | 后续批次 | P1名义派息不依赖停复牌/价格，无调度修改；原盘后时效规则及此前恢复证据保持，不能称本批重新实采停复牌 |
| S10 | 本批执行保留阻断；回购汇总及区间现金流后续P3 | 正式查询和桌面均保留回购准备失败、主题阻断；同一准备检查独立名义派息已计算。未将空查询当回购0 |
| S11 | 后续批次P4及持仓契约 | 相关产品明确功能未实现；未计算持仓收益/稀释、不改变001228未知详情结论 |
| S12 | 本批执行适用P0＋P1 | 最终实现文档审阅、统一门禁exit0、同包真实桌面、正常关开及配置/48保存设置/身份核实通过；实现与本证据提交一并推送main，远程最终精确身份见交付答复。S3/P2不包含在本批能力 |

## 验证命令和证据

命令均在项目根目录，Python为`.venv/Scripts/python.exe -X utf8`；完整本机过程在`build/returns-p0p1-20261022/`，该目录不提交。脱敏稳定证据随最终验收更新。

| 操作 | 退出码 / 结果 | 证据 |
| --- | --- | --- |
| pytest早期领域/准备缓存/范围/复权6文件，basetemp=build/pytest-returns-domain-2 | 0，114 passed | 开发结果；不代表桌面 |
| pytest tests/test_distribution_ui.py tests/test_capital_ui.py | 0，5 passed | offscreen开发交互；不冒充真实桌面 |
| pytest tests/test_distribution_cache.py tests/test_distribution_ui.py | 0，3 passed | 范围、重查、缓存及撤销旧future |
| pytest tests/integration/test_distribution_pipeline.py tests/integration/test_capital_archive.py tests/integration/test_adjustment_pipeline.py，私有13348 | 1，54 passed/5 failed | integration-1.xml/log；5个新用例模拟未提供报告期目录，已补一完整合成期夹具，非生产来源故障 |
| pytest tests/integration/test_distribution_pipeline.py，私有13348重跑 | 0，5 passed | integration-2.xml；源规范化→Redis→统一归档→正式summary；只读0业务DML、pending0；私有UUID库与Redis清理 |
| formal_audit.py | 0 | [生产只读证据](shareholder-return-p0p1-query-2026-10-22.json)，时间逐结果记录；无来源请求/collector/archiver，SQL只读守卫 |
| Ruff / Mypy | 0 / 0，13严格范围文件 | 不以静态等价代替业务行为 |
| pytest最终领域/界面13文件；basetemp=build/pytest-returns-final-domain2 | 0，189 passed/2既有Qt弃用warnings | [逐例结果](shareholder-return-p0p1-tests-2026-10-22.json)；原复权行为、Decimal、事件资格、边界、缓存、页面取消 |
| pytest tests/test_documentation_contracts.py tests/test_documentation_build.py tests/test_preparation_directory.py tests/test_preparation_progress.py | 0，35 passed | 同上逐例结果；早期一次误写不存在test_preparation_scope.py导致exit1/no tests，纠正文件清单后执行，不算通过证据 |
| measure_dividend_capacity.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/returns-p0p1-20261022/dividend-capacity.json --proxy-only | 0，原预算全部通过 | [真实新测量](shareholder-return-p0p1-capacity-2026-10-22.json)：637期、58614来源行、56168保留后SQL行、638代理请求、直连/回退0、pending0；完整比较及自有SQL/Redis清理通过。相差不是删除历史后凑等量 |
| documentation_build.py generate；documentation_contract.py review/check；verify_documentation.py；verify_database_design.py；architecture_contract.py check；assembly_contract.py check；verify_foundation_ui.py | 均0 | 143帮助主题、414文档/2488链接/55表、415模块/1492导入/0新债务；源与正文最后修改后已最终审阅。只读复用且存储语义未变的逐项理由登记documentation-review.json，不放宽规则 |

自有13348已实核UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir、四系统库和其他用户会话0后正常启动，PID2984。仅供隔离测试；已于UTC2026-10-21T19:27:33正常SQL SHUTDOWN，端口关闭，数据目录保留，见[正常关闭原记录](shareholder-return-p0p1-desktop-2026-10-22/private-mysql-close.json)。生产MySQL及共享Redis不停止、不重启、不清空。

## 正式发布、同包桌面和最终保留核实

唯一正式入口`.\verify-release.ps1`退出0，release `31a0cedf046e4a27ac5985dc96e4e02b`为原工具生成的`committed/passed`。冻结干净实现HEAD及全部输入后执行完整门禁：4037 passed、5 skipped、20 warnings，2658.51秒；5项均为`test_state_unit_isolated.py`既有显式opt-in drill，未执行不计通过，本批必需新增回归全部执行。完整[发布日志](shareholder-return-p0p1-desktop-2026-10-22/release.log)与[原工具发布身份摘录](shareholder-return-p0p1-desktop-2026-10-22/release-identity.json)保留。门禁本身明确不证明真实桌面，桌面事实单独记录如下。

正式`dist/Empire/Empire.exe` SHA256为`fb789f7524fc93a725e5b1dd1712066293af4efafdf93ed4602f76718225ba42`；安装目录产品树摘要为`f6debd5396b419e3385832f9133f25d9db0ac96220edf3577e33ef885e3b59a2`。从`C:\Windows`调用同一EXE的`doctor`退出0，真实MySQL3307及Redis均连接；原B4定点诊断退出2，保留原失败，详见[已安装包CLI原记录](shareholder-return-p0p1-desktop-2026-10-22/installed-cli-audit.json)。配置未作为公共包资源。

真实桌面使用computer-use技能的`@oai/sky`，未用离屏结果替代。全部原始时间、窗口身份和可访问树见[逐步原观察](shareholder-return-p0p1-desktop-2026-10-22/observations.json)，截图字节摘要见[文件清单](shareholder-return-p0p1-desktop-2026-10-22/files.json)。以下时间为北京时间2026-10-22，原JSON时间为UTC。

| 实际操作与范围 | 结果 / 原始截图 |
| --- | --- |
| 数据准备→长期价值研究→股东回报/稀释→000001、01-01～10-20→检查 | 03:32:43检查完成；6必需输入仍有1阻断，回购仍有缺口/不可用；独立派息已计算，其余四项功能未实现。[主题结果](shareholder-return-p0p1-desktop-2026-10-22/prepare-result.png) |
| 分红送转→具体产物 | 两笔明确实施，逐笔业务键、范围、单位、实际证据时间及0.609/6.09可见；明确非到账现金。[准备详情](shareholder-return-p0p1-desktop-2026-10-22/prepare-dividend-product.png) |
| 返回顶部→再次检查本次用途 | 实际检查时间变为03:34:00；结果重算、来源证据时间不刷新，原始观察`prepare-recheck-result` |
| 查看选中数据→现有分红页→填写同范围→名义派息汇总→计算 | 完整证券单元28条，按闭区间选中2条；独立手算预期一致。[正式分红汇总](shareholder-return-p0p1-desktop-2026-10-22/summary-main-result.png) |
| 起日01-01，止日依次06-11、06-12、09-23、09-24，每次改变后计算 | 逐次0/0.36/0.36/0.609元/股；改变后旧结果撤销为未检查。[失效](shareholder-return-p0p1-desktop-2026-10-22/boundary-0611-invalidated.png)、[完整空范围0](shareholder-return-p0p1-desktop-2026-10-22/boundary-0611-zero.png)、[首笔边界](shareholder-return-p0p1-desktop-2026-10-22/boundary-0612-result.png)、[第二笔前日](shareholder-return-p0p1-desktop-2026-10-22/boundary-0923-result.png)、[第二笔当日](shareholder-return-p0p1-desktop-2026-10-22/boundary-0924-result.png) |
| 恢复止日10-20→换600000→计算 | 独立1笔0.42元/股、4.2元/10股、完整单元26条；独立预期来自原正式逐笔0.42×10。[换证券结果](shareholder-return-p0p1-desktop-2026-10-22/switch-600000-result.png) |
| 换600938→计算 | 数据阻断、实际证据时间缺少，未将未知空集显示为0；原历史失配独立保留。[阻断](shareholder-return-p0p1-desktop-2026-10-22/switch-600938-blocked.png) |
| 回000001→未检查→重新计算 | 旧证券阻断撤销，重算恢复2笔0.609；未串用其他证券或日期缓存。[撤销](shareholder-return-p0p1-desktop-2026-10-22/switch-back-000001-invalidated.png)、[重算](shareholder-return-p0p1-desktop-2026-10-22/switch-back-main-result.png) |
| 点击分红数据说明 | 现有数据说明、日期及金额口径可见；结果正文包含名义含税当期股、非到账、无价格/回购依赖、非历史信号等限制。[说明](shareholder-return-p0p1-desktop-2026-10-22/dividend-help-visible.png) |
| 标题栏正常关闭→窗口消失/Empire进程退出→同EXE重新打开 | 无强杀、锁清理或单实例旁路；窗口5248576正常退出，重开窗口6885050/PID14168响应、可见、本地服务已连接。[正常重开](shareholder-return-p0p1-desktop-2026-10-22/desktop-reopened.png) |

重开取证辅助函数最初两次仍引用关闭前旧窗口，返回`foreground window did not report a process id`；查明后改用工具返回的新窗口，截图恢复。记录的是取证脚本窗口绑定修正，没有产品修改或重发包；未把失败截图当通过。

最终命令`.venv/Scripts/python.exe -X utf8 build/returns-p0p1-20261022/post_release.py post-release-final`退出0，[原输出](shareholder-return-p0p1-desktop-2026-10-22/post-release-final.json)证明EXE/产品树未变，两份config及插件偏好字节摘要与开工相同，48保存设置数量及内容摘要相同，生产UUID相同，global pending=0，B4原错误ID仍存在。应用保持重新打开；保留设置核对不输出配置正文。final文档状态整理未改产品代码、权威帮助或安装包。

结案状态更新后再次执行`documentation_contract.py review --note <本批结案具体说明>`（保留此前5项精确未改存储契约理由）、`documentation_contract.py check`、`verify_documentation.py`均退出0，414文档/2511链接/55表；再次运行`pytest tests/test_documentation_contracts.py tests/test_documentation_build.py tests/test_preparation_directory.py tests/test_preparation_progress.py --basetemp build/pytest-returns-closure-docs --junitxml build/returns-p0p1-20261022/closure-docs.xml -q`退出0，35 passed/10.59秒，[原JUnit](shareholder-return-p0p1-desktop-2026-10-22/closure-docs.xml)。`git diff --name-only e6374ea -- src tests scripts sql config Empire.spec`为空；最终新增内容仅动态状态、审阅记录及本次证据，不将证据提交误标为另一份已重打包源码。

生产查询、真实桌面和合成/隔离证据分别列示；桌面没有人为篡改生产数据制造同数异键、金额缺失或歧义。此类反例由上方开发/隔离证据覆盖。Redis离线通过隔离/合成测试回SQL验证，不停止共享Redis。本批无采集解析实质修改；完整容量实测仍依现有正式管线使用严格代理，不能混作本批30股新增采集验收。

## 保留失败和交付限制

600938等完整历史单元失配、B1空名债券、B2原46缺口、B3历史超集/未知详情及B4确切错误ID均保持原结论；本批不请求已知无新线索原来源，不删除历史和错误ID。当前回购集合失配及陈旧证明保持失败。主案例通过只证明指定范围的名义含税当期股派息，不是到账现金、不保证历史当时可知，不代表整个股东回报与稀释主题已完成。
