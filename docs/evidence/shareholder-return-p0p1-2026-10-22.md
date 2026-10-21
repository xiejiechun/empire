# 股东回报与稀释：首批P0＋P1执行账本

2026-10-22，**已实现、开发验证中；正式发布及真实桌面待验收**。仅实施[已批准方案](../shareholder-return-analysis-plan.md)P0＋P1；P2～P4、股息率、持仓到账现金/现金收益、回购支出汇总和稀释计算未实现。原主题仍检查四资本，回购失败仍阻断主题。A～F已验收状态保持，B1～B4及回购历史失败不冲销。

## 现场和实现

起点main/远程`db21f1d7d3be439fe495b57d8bbb8a1f85c2b75f`，开工工作区干净；现有修改均为本批。生产MySQL3307 UUID `77f9ba30-b666-11f1-81c5-380525361d4e`。旧release `a62017f2868244ffb86e4bf2c7dd7f02`，EXE SHA256 `9a89eee2b4da1b2be09346d251272e6f3c16269fe295931100a847fbf6cedc43`。复核时48份保存设置，待归档0；未修改配置、偏好、网络/任务/调度。后续状态仍按实际采集变动核实。

`dividends.query.distribution_summary`复用同一REPEATABLE READ只读快照内的证券身份、完整单元键/内容/SQL证明；Redis仅按既有可信摘要补充实际证据时间，缺失/不可用回SQL，不刷新证明。完整证明后再按闭区间除息日筛选。结果包含证券、用途、范围、实际证据时间与检查时间、完整单元摘要、逐笔键、含税金额和限制。Decimal精度60，逐笔不提前舍入；每10股为最终每股值×10。缺证明/身份/必需金额/日期/事件资格或歧义阻断，不填零。

原复权`contract.actions`的事件资格/歧义及数值错误规则迁入唯一公开`capital_actions.event_rules`，复权contract/inputs/query及测试调用方同步迁移；原入口退役，无转发层。默认复权首日归一为左开右闭，分红汇总显式闭区间、不依赖送转分项（名义当期股口径），两者边界分别验证。完整历史记录和预案保留；不按金额/报告期相似合并经济事件。

现有准备报告/详情增加具体产物；已有检查请求自动计算名义派息，报告缓存绑定新契约版本，范围改变独立身份、重新检查重算。原主题检查保持。分红页增加“名义派息汇总”，使用原证券/日期框，变化立即撤销旧结果；不依赖列表分页、状态筛选、价格或回购。未指定范围为未检查；计算结果分别显示已计算、数据阻断、来源受限，其余本批未实现产物明确显示功能未实现。

无采集/解析、来源协议、业务身份/表或DDL变更；不启动迁移，无新增并行准备、计算存储、下载或归档路径。不适用随机30股实采准入；本批只读生产查询不能冒充实采通过。因资本源码绑定变化，另按现行冻结工具实际重测完整分红容量；不更改历史报告或预算。

## 本批验收矩阵

| 方案ID | 批次及理由 | 本批实际验证 / 当前结论 |
| --- | --- | --- |
| S1 | 本批执行：P1主案例 | 生产只读重新核实两键和0.36/0.249，独立算式360/1000+249/1000=609/1000元/股、6.09元/10股；真实桌面待验收 |
| S2 | 本批执行独立性；O3数值及补价格属后续P2 | 生产复权仍因无归档日行情阻断；同输入名义派息已计算；股息率/持仓现金明确未实现，未加价格采集 |
| S3 | 后续批次P2 | 股息率尚无计算，禁止用理论复权/原始记录代替，未执行补价或股息率数值验收 |
| S4 | 本批执行 | 正式只读四边界独立预期0/0.36/0.36/0.609；600000独立结果；合成UI验证换证券/日期取消旧查询；真实桌面待验收 |
| S5 | 本批执行 | 正式600938仍数据阻断；生产历史只读保留。开发预案+实施只计实施且输入不变；其他原失败记录不清理 |
| S6 | 本批执行 | 合成同日并列、跨范围同报告期不同除息日、未知日期/金额、重复键、状态/税口径未知均拒绝；不同报告期独立两笔可算 |
| S7 | 本批执行 | 私有SQL同数异键、同键异内容、缺记录和缺proof在日期投影为空时仍阻断；完整证明空范围为0；范围外未知证券已有精确单元回归 |
| S8 | 本批执行P1时间/缓存；逐修订版本建设后续 | 正式historical_signal来源受限；私有SQL/已有可选摘要失配、过期、超前、离线反例；缓存读不重算/不延TTL，force及证券/日期变化重算 |
| S9 | 后续批次 | P1名义派息不依赖停复牌/价格，无调度修改；原盘后时效规则及此前恢复证据保持，不能称本批重新实采停复牌 |
| S10 | 本批执行保留阻断；回购汇总及区间现金流后续P3 | 正式回购准备失败，原主题条件未删除；合成验证主题失败不传播到独立名义派息。未将空查询当回购0 |
| S11 | 后续批次P4及持仓契约 | 相关产品明确功能未实现；未计算持仓收益/稀释、不改变001228未知详情结论 |
| S12 | 本批执行适用P0＋P1 | 最终文档审阅、门禁、同包桌面/正常关开/配置与身份/推送待执行；S3/P2不包含在本批发布能力 |

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

自有13348已实核UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir、四系统库和其他用户会话0后正常启动，PID2984。仅供隔离测试；任务结束正常SQL SHUTDOWN，生产MySQL及共享Redis不停止、不重启、不清空。

## 保留失败和交付限制

600938等完整历史单元失配、B1空名债券、B2原46缺口、B3历史超集/未知详情及B4确切错误ID均保持原结论；本批不请求已知无新线索原来源，不删除历史和错误ID。当前回购集合失配及陈旧证明保持失败。主案例通过只证明指定范围的名义含税当期股派息，不是到账现金、不保证历史当时可知，不代表整个股东回报与稀释主题已完成。
