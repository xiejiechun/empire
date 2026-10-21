# P2 区间名义现金股息率实施账本

状态：**已实现、开发通过、正式发布；固定业务范围同包真实桌面已通过。严格quote代理全样本仍失败，P2全部适用要求尚未验收。** P0＋P1保持原结案；原B项、600938与回购失配不结案。P3/P4未实施。以下前像、早期失败及候选验证保留，正式发布与桌面事实见末节。

## 前像与最小范围

- main与origin/main为9e5bfeabe23e16d3e8a74932bcc516fe66338877；开工工作区干净。
- P1正式EXE仍运行，发布31a0cedf046e4a27ac5985dc96e4e02b。配置及48项保存设置前像见build/returns-p2-20261022/preflight.json。
- 固定000001.SZ / 2026-01-01～2026-10-20原正式无价格失败保留；首次脚本未启动可选Redis，分红按旧SQL证据阻断。补充启动Redis后只读复核分红仍0.609元/股，没有刷新证明。
- 一次共享代理来源核查得到2026-10-20盘口价11.44、来源时刻15:38:33；随后正式有限采集已完成，不能将最初probe本身当作归档证据。

复用dividends.query与P1完整单元、事件资格及Decimal；同一RR READ ONLY SQL快照读取分红、日历、证券日及停复牌。可选Redis只匹配SQL内容补充证明，SQL不可用或不匹配不能放行。既有准备缓存恢复时重新核验具体产物，旧报告不授权新数值。

分母仅用正式日历截止日对应最近已结束交易日，范围含尚未结束交易日则阻断；非交易日明确显示实际分母日。不因停牌或缺价退回更早日。不做年度化、TTM、成本收益或历史信号。

股数基准守卫：本批简版需要区间每个正式交易日的已验证未复权收盘快照及正数总股本，一致生命周期、股本不变，并要求区间实施分红的送转明确为零；任何缺日、送转或股本变化阻断。它是日频来源快照证明，不声称逐时股本版本或严格历史可知。特殊事件/关联歧义仍由共享资格规则拒绝。只读计算，不新增表、数据集、持仓或价格来源。

现有开盘啦采集仅全池规划。本批在同一collector/control/CLI增加可选显式证券与日期范围，保留单实例、单任务、原子断点、失败不推进、统一归档及取消；范围为本次运行参数而非保存策略。日常无参数行为不变，断点绑定范围，不复用别的范围完成标记。没有解析或表结构变化；仍按实质采集修改执行随机30股加固定失败证券的代理实采，来源失败如实保留。

## 验收矩阵

| 项目 | 本批范围与独立预期 | 当前状态 |
| --- | --- | --- |
| S1/S3（本批执行） | 固定000001分红0.609，正式归档价格独立取值，手算0.609/价格×100；真实桌面展示公式及来源时间 | 开发、正式只读数值及同包桌面通过；0.609/11.44×100=5.3234265734…% |
| S2（本批执行） | 原缺价失败保留；缺价仍阻断股息率、不阻断P1 | 开发通过，原证据保留；10-21真实缺价阻断 |
| S4（本批执行） | 闭区间、非交易日、证券切换、重新检查、缓存撤销 | 开发通过；同包桌面10-18采用10-16，切换及重算撤销旧结果；P1原闭区间边界回归通过 |
| S5/S7（本批执行） | 600938、同数异键、同键异内容、少记录及空集完整证明保持 | 开发/隔离通过；同包桌面600938仍阻断，000001截至6-11完整空范围为0%；未篡改生产造反例 |
| S6（本批执行） | 预案不计、未知日期金额及实施歧义拒绝、送转/股本变化拒绝 | 开发通过；不篡改生产制造反例 |
| S8（本批执行） | historical_signal受限；Redis不可用/失配/过期回SQL；旧缓存不得沿用新输入 | 开发通过；正式历史信号受限 |
| S9（本批执行） | 未收盘、来源盘中、错证券、复权误用、停牌、零负价、股本缺失 | 开发/隔离反例通过；同包真实10-21缺价准确阻断，不退用10-20价格 |
| S10（本批执行） | 回购主题阻断不传播独立O2/O3；原失败保留 | 开发及主题真实桌面通过；主题仍阻断，O2/O3独立已计算 |
| S11 | P3/P4、持仓到账、回购及稀释计算 | 后续批次，本批不实施 |
| S12（本批执行） | 最后文档审阅、专项/隔离集成、唯一发布、同包桌面及正常关开、配置/保存设置/main身份 | 门禁exit0、4077 passed/5原opt-in skipped；同包桌面及正常关开、配置/48设置保留通过；结案文档与远程核实见末节 |

独立开发预期：0.609 / 12 × 100 = 5.075%，仅合成反例，不是生产价格。生产只读查询、合成输入、真实来源及桌面证据分别记录。未满足项不标完成。

## 当前实现及开发证据（发布前）

- 实现：dividends.query新增dividend_yield计算贡献，复用P1完整单元/共享事件资格与Decimal；原复权共同调用kaipanla.closing。无新表、数据集、旁路价格或双写。既有分红页与准备详情显示独立产物；P3/P4仍未实现。
- 固定范围正式命令经collect_audit.py观察后调用原CLI：`collect-intraday --kind quote --securities 000001.SZ --start 2026-01-01 --end 2026-10-20 --proxy-priority`，exit0。production-collection.json：190必要证券日、202代理请求（含上市依赖）、直连/回退0，来源/入队/正式查询键集合及规范内容一致，pending0；batch 09274027643d4bf194fdb10f7f2a15e5。此轮是开发候选采集，不冒充最终包验收。
- 早期候选错误将有限采集完成提升为全池每周复核；现实现保留原全池标记而不推进，差范围完成断点也不短路。对本轮确切batch通过公共advance_checkpoint CAS仅失效last_review/review_token，owned-review-invalidation.json记录前后；不改业务内容、采集位置或保存策略，不删共享锁/键。
- 新停牌检查最初将早年未知复牌无限外推，production-collection.json保留真实阻断。修复后同一事务核验现行来源日历/完整性版本、SQL连续覆盖与盘后确认；按完整五列来源日身份检查未知记录，明确生效停牌仍阻断。历史记录全部保留，未修改来源解析。隔离反例覆盖旧未知、同record_key异证券、同日真实未知、开盘复牌、盘中复牌和盘前确认。
- formal-query.json为只读正式查询复核：0.36＋0.249＝0.609元/股；正式2026-10-20原始价11.44、来源时刻153833000，SQL观察北京时间2026-10-22 04:34:50.323266；独立按逐笔Decimal求和后手算百分比5.323426573426…，与实现一致。600938仍数据阻断、historical_signal来源受限、截止10-21缺价阻断。SQL/Redis证明未刷新。
- `pytest`相关191项exit0，224.14秒，domain-final.xml；执行期间最后增加停复牌现行版本守卫，因此P2七项隔离用例另行重跑，最终正式门禁仍须完整验证。独立规则86项exit0（rules-final.xml），strict13 mypy、Ruff、架构0新债务、精确装配及文档契约通过。早期失败JUnit/命令调用错误保留，不计通过。
- 新查询预算：20证券/3660日、完整分红单元最多2000条；quote每16日有界加载，停牌证据最多1000条。固定190日实际热查询另测3次，预算每次5秒；不声称冷缓存、全市场或最大范围吞吐。原容量因capital_actions绑定变化须真实重测，不能只刷新旧hash。

build/returns-p2-20261022为原始证据工作目录；必要开发、发布及桌面原证据已按原字节归档至docs/evidence，各目录files.json记录摘要。此节为发布前开发事实，容量、正式发布及桌面后续结果见下文。

## 本批quote有限范围严格代理实采

命令：`.venv/Scripts/python.exe -X utf8 scripts/verify_kaipanla.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/returns-p2-20261022/quote-source.json --seed 20261022 --random-count 30 --proxy-only --kinds quote --days 2026-10-20 --fixed-days 2026-09-28 2026-09-29 2026-09-30 --bounded-request`，**exit1，严格全样本仍失败**。未修改来源解析，未重跑其他六产品。此次为新增显式范围执行必要的quote固定回归；不继续重复原失败请求，不作为原B2结案。

5580只正式池摘要0b51dfd87fc3fb11573a0db98dfa6eff4949107f0a782f21d4d6a4415880fa39，种子20261022；30随机及固定五只原名单均见quote-source.json。随机30在10-20全部经真实来源→规范化→Redis→统一归档→正式查询通过，sample_30_met=true；主范围35个必要单元34有效/1失败，47代理；历史固定15单元12有效/3失败，27代理，直连/回退0。有效来源与正式查询集合和规范内容相同，两轮pending0、失败不推进完整断点。

失败均为002731.SZ：10-20及09-28/29/30接口未成功，不能证明空日。该报告没有原始错误码，不将原B2的1017擅自写成本轮已观测错误码，也不据此猜停牌/退市/权限。需要来源恢复这些精确证券日的quote响应，才能完成全样本严格采集验收；当前保留失败、股息率对缺少必需价格的范围仍阻断。000001原固定范围成功不覆盖该限制。

自有实例实际server_uuid=a3e8a5eb-cb64-11f1-8ddf-380525361d4e、13348，UUID数据库及Redis namespace归属守卫有效；shutdown/sql/redis/sql_lock/connections/instance_lock六清理全部true。未写生产业务、未删除共享数据。新停牌版本守卫后P2隔离七项exit0（snapshot-final.xml，15.93秒）。

## 容量与输入绑定

`scripts/measure_dividend_capacity.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/returns-p2-20261022/dividend-capacity.json --proxy-only`，exit0。[本轮真实新报告](shareholder-return-p2-capacity-2026-10-22.json)：637报告期、58614来源行、638代理请求，直连/回退0；正式存储56168条，当前集合56138条，30条历史键逐项保留。正文23376501字节、最大447字节、10次正式查询最大2.799毫秒以下，原预算全部通过，pending0及六项归属清理true。数据库设计卡改绑新实测，旧报告原样保留，没有改测量工具、协议、阈值或DDL。

新分析只读热查询3次128.512/113.634/158.969毫秒，均小于预先登记5000毫秒、190日证据与输入hash一致；[查询测量及EXPLAIN](shareholder-return-p2-development-2026-10-22/query-capacity.json)记录真实SQL访问计划与105条只读语句（共三次）。不宣称冷缓存或最大范围容量。观察进度时恰遇私有库正常清理完成，capacity_progress.py一次报Unknown database；这不是测量失败或需要重建的生产库，完整容量原命令仍exit0。

[开发原证据目录](shareholder-return-p2-development-2026-10-22/)保存原缺价、代理probe、正式采集、早期失败JUnit、最终回归、正式只读结果及严格来源失败。所有结果由实际命令生成，未手改passed或历史原失败；此为发布前证据，后续发布/桌面单列。

发布前全量非集成命令：`pytest -m 'not integration' -xq --basetemp build/pytest-p2-unit-all --junitxml build/returns-p2-20261022/unit-all.xml`，exit0，3466 passed / 12 opt-in skipped / 604 integration deselected / 20 warnings，171.05秒。该命令不冒充完整发布集成；正式门禁仍将启用EMPIRE_INTEGRATION并验证私有UUID全schema。冻结性能工具、release_lock、历史基线与阈值未改。

## 正式发布身份与实际命令

实现提交为`dba889f8b7aeb086b7d8264971a9b1c2a62d9b3a`。唯一正式发布命令`.\verify-release.ps1`，环境`EMPIRE_TEST_MYSQL_SETTINGS`指向已核实的私有13348设置文件，**exit0**。release `4c672429732f48669159d410a91917d9`由工具实际写成committed/passed；完整4077 passed、5 skipped、20 warnings，2676.93秒。5项均为`tests/integration/test_state_unit_isolated.py`既有显式opt-in drill，不算已执行；本批新增适用用例均已执行。隔离集成、公共完整集合/恢复、四档模拟容量、打包、包内/搬移smoke和配置引导均在该轮。模拟容量不等于真实来源吞吐。

- 正式EXE SHA256：`7daaf84de6a00f36eb745a980ab3d632e07da1c07d0c5dd33531d3231a54f576`。
- 产品目录树SHA256：`adb571c2a4a3ced91065eb576d447a24d9f123ef57bcbe6820843eb170687585`。
- [原发布journal](shareholder-return-p2-release-2026-10-22/publication.json)、[完整日志](shareholder-return-p2-release-2026-10-22/release.log)、[全部输入](shareholder-return-p2-release-2026-10-22/inputs.json)、[原JUnit](shareholder-return-p2-release-2026-10-22/generated/release-tests.xml)和[文件清单](shareholder-return-p2-release-2026-10-22/files.json)按原字节归档，未改passed、阈值或冻结工具。
- 在结案文档任何修改前，`build/returns-p2-20261022/audit_release.py <release_id> <实现提交>` **exit0**，核对2108个输入、58个保留输出及25步骤；无输入失配，见[原审计](shareholder-return-p2-release-2026-10-22/release-audit.json)。归档保留62个文件共3202400字节，包含上述原始输出和日志。
- `build/returns-p2-20261022/installed_cli_audit.py` **exit0**：从`C:\Windows`运行同一EXE，`doctor`真实MySQL/Redis连接**exit0**。quote/dividends/B4定点doctor各**exit2 partial**，保留项目历史缺口及原错误，不写作全部诊断通过，见[实际命令/退出码](shareholder-return-p2-desktop-2026-10-22/installed-cli-audit.json)和同目录四份原日志。

正式查询与桌面使用现有唯一查询路径；新`dividend_yield`登记在`dividends.query`，没有创建第二准备系统或生产写库脚本。复权原收盘资格调用迁入共享`kaipanla.closing`，P1事件规则/完整证明复用；没有保留旧收盘判断副本、新兼容入口、双写或启动迁移。

## 同包真实桌面

使用computer-use技能的`@oai/sky`操作正式EXE。原始窗口、实际UTC时间和可访问树见[逐步原观察](shareholder-return-p2-desktop-2026-10-22/desktop/observations.json)，截图与JSON字节摘要见[文件清单](shareholder-return-p2-desktop-2026-10-22/files.json)。没有用离屏、CLI或模拟结果冒充桌面；下表时间为北京时间2026-10-22。

| 实际入口、范围与操作 | 观察结果与证据 |
| --- | --- |
| 数据准备→长期价值研究→股东回报/稀释→000001、01-01～10-20→检查本次用途 | 05:54:48检查完成；6必需项2通过/3有限制/1阻断，回购仍有缺口且不可用。O2/O3独立已计算，其他产物功能未实现；[主题结果](shareholder-return-p2-desktop-2026-10-22/desktop/preparation-result.png) |
| 分红→具体产物→向下查看 | 两笔精确业务键、0.609元/股及6.09元/10股；实际分母10-20、11.44元、来源盘口15:38:33、SQL观测04:34:50.323266、公式和190日股数基准证明可见；[公式](shareholder-return-p2-desktop-2026-10-22/desktop/prepare-yield-formula.png) |
| 返回顶部→重新检查→导出报告 | 05:57:14重新检查完成；来源证据时间不刷新。通过正式导出按钮保存[原JSON](shareholder-return-p2-desktop-2026-10-22/desktop/preparation-export.json)；[重新检查](shareholder-return-p2-desktop-2026-10-22/desktop/prepare-recheck-result.png) |
| 查看选中数据→分红送转→名义派息汇总→填000001、01-01～10-20→计算区间名义现金股息率 | 06:02:54已计算，两笔0.36/0.249、完整单元28条；[逐笔](shareholder-return-p2-desktop-2026-10-22/desktop/dividend-page-fixed-result.png)、[实际价格公式](shareholder-return-p2-desktop-2026-10-22/desktop/dividend-page-yield-formula.png)显示0.609/11.44×100=5.323426573426…%。与独立逐笔手算一致，不硬编码旧值 |
| 改止日10-21→计算股息率 | 旧结果先撤销为未检查；06:03:48数据阻断，明确缺少精确分母价格或区间股数快照，不能改用更早价格；[阻断](shareholder-return-p2-desktop-2026-10-22/desktop/missing-price-blocked.png) |
| 同10-21范围→计算名义派息 | 06:04:04独立派息仍已计算0.609元/股、6.09元/10股；[独立可用](shareholder-return-p2-desktop-2026-10-22/desktop/distribution-usable-despite-price.png) |
| 改止日10-18非交易日→重新计算 | 06:04:33已计算；正式日历实际分母10-16，未复权11.50元、来源15:37:39，0.609/11.50×100=5.2956521739…%，188个基准日；[实际分母](shareholder-return-p2-desktop-2026-10-22/desktop/nontrading-denominator-visible.png)。这是边界反例，不替换原10-20正例 |
| 改止日6-11→重新计算 | 06:05:23已计算，完整分红单元28条、区间0笔、0元/股，精确分母6-11为11.30元、104个基准日，0/11.30×100=0%；[完整空范围](shareholder-return-p2-desktop-2026-10-22/desktop/proved-empty-zero.png) |
| 换600938、恢复止日10-20→计算 | 06:06:13数据阻断、来源证据缺少、0完整单元/1未证实，未将未知空集填0；原历史失配仍阻断；[历史反例](shareholder-return-p2-desktop-2026-10-22/desktop/600938-still-blocked.png) |
| 回000001→刷新正式逐笔→计算 | 输入改变后撤销旧结果，逐笔浏览重新显示平安银行；06:07:35恢复原2笔及0.609，重算不串用其他证券或范围；[恢复结果](shareholder-return-p2-desktop-2026-10-22/desktop/restored-fixed-result.png) |
| 标题栏正常关闭→无窗口/无Empire进程→同EXE重新打开 | 原窗口14881126正常退出，新窗口9705588响应、可见，本地服务已连接，待归档0；[关闭窗口记录](shareholder-return-p2-desktop-2026-10-22/desktop/normal-close.json)、[进程核实](shareholder-return-p2-desktop-2026-10-22/desktop/normal-close-processes.json)、[正常重开](shareholder-return-p2-desktop-2026-10-22/desktop/normal-reopened.png)。最终保持打开 |

导出模态的UIA元素312曾返回`element is not available in cached app state`；fresh窗口/截图后用坐标完成文件名与保存，原观察保留。它是取证辅助缓存错误，不是产品代码修改，未把错误截图算作通过。

生产桌面未人为造零负价、错证券、复权价或股本变化。这些反例、盘中/尚未收盘、旧响应、修订缓存失效及Redis不可用回SQL由开发/隔离证据执行；不重启共享Redis验证离线。`tests/test_dividend_yield.py`、`tests/integration/test_dividend_yield_pipeline.py`、`tests/test_distribution_cache.py`及P1/原复权回归均包含在本次正式JUnit中。手算合成12元仅预期5.075%，不作为生产价。

## 保留、清理与结案边界

最终命令`.venv/Scripts/python.exe -X utf8 build/returns-p2-20261022/post_release.py post-release-final` **exit0**，见[原只读核实](shareholder-return-p2-desktop-2026-10-22/post-release-final.json)：EXE/产品树相同、两份config及插件偏好字节摘要保持、48项SQL保存设置数量/内容摘要保持、生产UUID保持、global pending=0、原B4错误ID仍存在。该脚本仅只读查询，不刷新证明、不改变保存策略。此前[桌面前核实](shareholder-return-p2-desktop-2026-10-22/post-release-before-desktop.json)单独保留。

自有MySQL13348在核实实际UUID、datadir、仅四系统库和其他客户端0后，通过`stop_owned_mysql.py`正常SQL SHUTDOWN，**exit0**，见[关闭原记录](shareholder-return-p2-desktop-2026-10-22/private-mysql-close.json)。未结束生产MySQL、清空/重启共享Redis、删除锁或历史业务记录。原B4错误未解决所以未清理；本批没有将来源失败当作已修复错误清除。

尚未满足的严格准入精确为002731.SZ的2026-10-20及2026-09-28/29/30 quote响应。需要来源恢复这些原证券日的有效完整响应后，按原样本集合/内容/清队规则复核；当前不能证明其为空日，也没有原始错误码可解释更细原因。不会无限重复请求或换样。本批功能、固定业务范围及正式发布通过，**不等于严格采集全样本通过**。600938、B1空名债券、B2原46缺口、B3历史全集/未知增发及B4原错误保持失败或受限，回购继续阻断整个主题；historical_signal继续因稳定事件关联及逐修订可用日不足而来源受限。P3/P4、持仓现金、回购/稀释汇总未实现。

最终证据提交仅整理状态、README、审阅及原始证据；不改变该发布包的产品源码、权威帮助、测试、工具或SQL。远程提交与最后文档检查另记结案核实，包仍绑定上述实现提交，不能把后续证据提交称为另一份已打包源码。

结案相关文档/准备目录回归`pytest tests/test_documentation_contracts.py tests/test_documentation_build.py tests/test_preparation_directory.py tests/test_preparation_progress.py --basetemp build/pytest-p2-closure-docs --junitxml build/returns-p2-20261022/closure-docs.xml -q`已exit0，35 passed/9.31秒，[原JUnit](shareholder-return-p2-desktop-2026-10-22/closure-docs.xml)。最后状态修改后再次显式审阅，并执行文档生成一致性、契约、指南和同组回归；实际命令/退出码分别见同目录closure-build/contract/guides/regression.json及日志，未执行前不作为通过证据。
