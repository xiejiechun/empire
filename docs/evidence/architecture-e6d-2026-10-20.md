# E6d 解禁与行业解禁实施记录

当前状态：**最终开发验证通过**，尚未发布、未验收，不进入E6e。前批E6c结案`81dbf0d4b283a6d8fd5ab730f3cc3d142f2b6249`已push，2026-10-20 18:16通过现有只读共享代理`ls-remote`精确匹配；本地收据`build/architecture-e6c-20261020/remote-close.json`，直连超时保留。E6c包release `689a04ad03ee4cdba386f39438e704f3`不因文档结案改变。

## 前像、范围与生命周期

前像为上述干净main。开工正常Alt+F4关闭正式Empire，实际看到结束归档/关闭连接提示，fresh窗口列表无Empire；关闭前活动0/pending0、原业绩披露/报告失败2保留。自有13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`与原datadir核实，仅四系统库、无其他客户，与生产UUID不同；两config/偏好摘要、冻结工具及原包身份核实通过。`py build/architecture-e6d-20261020/preflight_resource.py` exit0。工作结束须正常重开。

从当前正式源码重建，未应用整份草稿。两业务各迁contract/source/collector/dataset/query/ui，共12旧模块删除；旧→新精确表及实际字节前像在本轮`preimage.json`。调用方、测试patch、维护脚本、装配映射、coverage和所有权同步。`features/unlocks`与`features/unlock_industries`分别接回原贡献槽位；`sources/tdx_unlock.py`唯一拥有原PAGE/body/results，行业不再借用个股私有source，数值规范仍通过公开contract使用。无DDL、持久身份/字段/唯一键/用户策略变化，无兼容转发或双注册。

个股：完整月列表与每个必要证券/日期/原因请求组明细；列表事实record_key及共享明细group_key分别保留。初始化1990-01至下一自然年12月，支持显式月份；补列表变化/缺证明/空明细，每轮轮换历史月回查，fresh回查全部。行业：来源当前目录与估值基准冻结整轮，月行业完整集合，目录外历史保留。两者均按序校验入队，继续后批下载，仅整轮末等待归档；失败不跳过，提交后可重放，成功统一清队。Redis丢失重建来源/SQL计划，不承诺丢失业务消息恢复。公告可用日期、空明细、未知数量和来源覆盖限制保持原说明。

原verify脚本默认生产写入与自动保存默认策略已退役。现入口复用`source_verification`/`PrivateStorage`的实际UUID、owner、逐连接SQL守卫、取消与独立清理，禁止覆盖报告；容量入口复用同一资源生命周期，保留原样本规模、SQL、重复次数与阈值并增加全量内容核对，清理失败不PASS。个股`--sample`要求本轮全代理实际来源报告及当前source绑定；行业容量保持原已审来源seed，新实采另验。

## 验收矩阵与命令

以下`py`为`.venv/Scripts/python.exe`，`out`为`build/architecture-e6d-20261020`，测试配置为已核实13348的`build/architecture-evolution-20261019/mysql-settings.json`；凭据与owner原文不提交。

| 验收ID | 实际命令/证据 | 结果、限制与下一步 |
| --- | --- | --- |
| C1/C2身份顺序 | `py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` exit0 | 插件/任务/dataset/schema/页面及原槽位精确一致；首轮含未装配contract/source映射被拒绝，移除unused条目后通过，未放宽检查 |
| C3/C4边界/退役 | `py scripts/architecture_contract.py check --output out/architecture-1.json` exit0 | 404模块/1453导入、0新增债务、0剩余旧债务、45退役；原行业私有来源依赖已消除。最终再核 |
| R1～R4/U领域与隔离 | 显式`EMPIRE_INTEGRATION=1`及测试配置，`py -m pytest tests/test_tdx_unlocks.py tests/test_tdx_unlock_industries.py tests/test_tdx_unlocks_ui.py tests/test_tdx_unlock_industries_ui.py tests/integration/test_tdx_unlocks_archive.py tests/integration/test_tdx_unlock_industries_archive.py --basetemp build/pytest-e6d-domain -q --junitxml out/domain.xml` exit0 | 31 passed/59.03秒，无skip；共享组/出现次数、单位、同数异集、历史下报辅助count、版本冷热/重放、取消与入队独立推进。不是实采 |
| 资源/SQL工具 | `py -m pytest tests/test_source_verification.py tests/test_unlock_verification_tools.py ... --junitxml out/safety.xml` exit1 | 103 passed/3 failed，57.65秒：两个取消fixture缺execute属性；行业重复DDL尾分号被守卫拒绝。修fixture及去单句尾分号，不改共享守卫；重验中，原失败保留 |
| R2实际来源 | 未开始；个股冻结种子20261020，从当前正式股票池随机30并固定603027.SH | 完整月份1990-01、1996-05、2020-01/02、2025-10、2027-12，列表全市场且每必要group明细，逐股票（含真实空集）与全范围内容/集合核对，proxy-only/pending0。行业当前目录全部月行业独立核验，不充当30股票 |
| 容量/T3 | 两份旧绑定已因路径变化失效，新完整容量及原T3未完成 | 个股100000汇总/200000明细及原SQL/5次；行业120月×100行业及原6次。百万明细为线性预测，不冒充实际导入 |
| M/A1～A4/U1～U3 | 文档同步、最终审阅、完整门禁及同包真实桌面尚未完成 | 含分页/详情关联、行业筛选/基准、空态/帮助/独立启停、草稿滚轮/窄窗、48设置/45策略及两config/偏好、异cwd连接与正常关开 |

H3固定空名债券、开盘啦严格来源、资本历史准备、生产历史freshness和旧错误`38622b7215a44fe4a5224031bdf4d963`保留；E6e两日常错误待核查，不清理或抵销。整个优化未完成。

## 接续验证检查点（取代上表早期运行状态）

- 工具修复后`safety-2.xml`为106 passed/78.67秒/exit0；公共回归`public.xml`为345 passed/41.30秒/exit0。当前架构为404模块/1455导入/0新增与既有债务/45退役债务。strict mypy 8文件及相关Ruff通过。
- `py scripts/verify_unlocks.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --seed 20261020 --random-count 30 --proxy-only --timeout 1800 --output out/unlocks-live-1.json`真实exit0。run `803b285799b54edd941c9ad907289864`，source `0a10d90e1799d3044dbc20ac74f2d38d82b8ccb92ea559cf28a0325602521b07`。5579只池、种子及30随机加固定603027.SH保留原名单；六完整月三市场18单元，574列表事实/6154共享组明细，572代理请求、直连/回退0；31只各正式查询集合与内容一致，5只有记录、26只在声明月份为真实空集，固定证券2条。空集不解释为全历史无解禁。全市场必要group全部请求一次，完整单元、分页及每group正式详情逐项核对，本轮pending0。
- `py scripts/verify_unlock_industries.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --timeout 900 --output out/industries-live-1.json`真实exit0。当前目录2026-09～2028-08共24月703行，基准日2026-10-20；25代理请求、直连/回退0，逐月行业集合/内容/正式分页一致，pending0。按行业/月采集，随机30股票不适用。
- 两份最终来源报告均六项清理true、SQL/Redis remaining=false、errors空；报告旁ownership含私密owner，仅留build不提交。有限来源完整性通过不代表全历史数据准备通过；报告原preparation失败/限制保持，不能由pipeline通过冲销。
- 当前个股新容量正在执行，行业新容量、最终T3、文档审阅、正式发布与同包桌面仍未完成。E6d仍为已实现待验证，E6e未开始。桌面正常关闭；自有13348仍运行供本轮私有验证，不关闭生产3307/共享Redis，不清未解决错误。


## 最终开发退出证据

| 验收ID | 实际命令与退出 | 结果与限制 |
| --- | --- | --- |
| R2来源 | 上述两条verify命令均exit0；[个股原报告](architecture-e6d-unlocks-source-2026-10-20.json)、[行业原报告](architecture-e6d-industries-source-2026-10-20.json) | 当前源摘要一致；有限范围、随机名单及真实空集逐项保留，未改写preparation结论 |
| 容量 | `py scripts/measure_unlocks.py --test-settings <测试配置> --sample out/unlocks-live-1.json --output out/unlocks-capacity-1.json`及`py scripts/measure_unlock_industries.py --test-settings <测试配置> --output out/industries-capacity-1.json`均exit0 | [个股](architecture-e6d-unlocks-capacity-2026-10-20.json)原100000/200000行、100单元全量内容/关联及修订核对，导入26.6765秒/277512192字节；[行业](architecture-e6d-industries-capacity-2026-10-20.json)原12000行120单元、导入0.4101秒/2916352字节。全部原预算通过，重复DML0、修订1，五次/六次原始样本、EXPLAIN及六项清理完整。110万行仅线性预测。两设计卡指向新实测，全部现行容量绑定核实无失效 |
| T3 | `py scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings <测试配置> --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output out/performance-1.json` exit0 | [原协议报告](architecture-e6d-performance-2026-10-20.json)18项通过，无改工具/协议/历史基线/阈值；独占测量期间无同期测试、实采或构建 |
| M文档 | `py scripts/documentation_contract.py review --note <逐项审阅说明> --unchanged page:unlock_industries=<页面仅迁包、原筛选分页基准与窗口限制保持的具体理由>`、check、verify_documentation、verify_database_design均exit0 | 首轮review因行业页面正文未改变被拒绝，逐项审阅其操作与限制后登记具体等价理由，未修改门禁。250文档/1686链接，55表/49数据集/12JSON |
| M相关回归 | `py -m pytest tests/test_collection_rules.py tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-e6d-docs-2 -q --junitxml out/docs-2.xml` exit0 | 46 passed/25.14秒；此前误写不存在的单数test_documentation_contract.py而exit1/no tests，未计通过、未改变测试选择规则 |
| U3前像 | `py out/pre_release.py` exit0 | 四份最终来源/容量source摘要、配置偏好和bindings一致；48设置payload/updated_at及原偏好私密前像保留 |

上述早期“未开始/正在执行”仅为历史检查点。当前为开发验证通过；正式发布、同包配置/正式查询/真实桌面与结案push尚待执行，未进入E6e。


## 首轮正式门禁失败与修复

实现提交99efc9472b3183b4271933548958ebd447a6e08b的首轮唯一正式门禁run `b958223d1db74738b0616320a975c7ea`在step007全仓Ruff因三处I001退出1，尚未pytest/构建/发布切换，原E6c安装包保持。此前定向Ruff未覆盖builtin及两份既有领域测试。已修正仅import顺序，三个文件import多重集合和非import AST精确一致，FACTORIES顺序未变；未改检查工具。全仓Ruff及strict mypy重新exit0。失败原日志和failure.json保留。

源码摘要随修复改变，首轮来源/容量/T3不冒充最终证据；正在按相同池、种子、固定证券、月份和原协议生成新报告，不改旧hash。上述开发通过是首轮输入历史状态；当前等待最终重新验证、提交、完整门禁和同包桌面。


## 导入排序修复后最终重验

最终source摘要`38b3566901791de40e6449346769294ff141f5b5c93d254db82f2f4fb540125a`。使用同一正式命令，仅输出改为`unlocks-live-2-final.json`、`industries-live-2-final.json`、`unlocks-capacity-2-final.json`、`industries-capacity-2-final.json`及`performance-2-final.json`，个股容量sample明确改为本轮final实采；五条命令均真实exit0。

- [最终个股来源](architecture-e6d-unlocks-source-final-2026-10-20.json)：原池/种子/30随机+固定完整名单精确相同，18单元及31证券规范集合与首轮精确一致，572全代理、pending0、六清理true，无残留/errors。
- [最终行业来源](architecture-e6d-industries-source-final-2026-10-20.json)：24月703行、25全代理、pending0、六清理true，无残留/errors。
- [最终个股容量](architecture-e6d-unlocks-capacity-final-2026-10-20.json)：100000/200000行、原全部预算通过，导入28.3701秒、277512192字节；全100单元集合/正文/关联、重复DML0与修订1核验。
- [最终行业容量](architecture-e6d-industries-capacity-final-2026-10-20.json)：12000行120月、原全部预算通过，导入0.5287秒、2916352字节；全部单元内容、重复DML0与修订1核验。两容量配置/源码绑定及清理通过，两设计卡改指本轮新报告，没有修改旧报告hash。
- [最终冻结T3](architecture-e6d-performance-final-2026-10-20.json)：原命令18/18通过，correctness/cleanup通过；未改协议、工具、历史基线或阈值。
- [首门禁失败](architecture-e6d-release-failed-2026-10-20.json)及[三文件修复等价](architecture-e6d-import-order-fix-2026-10-20.json)保留。正式构建尚未开始，同包桌面及结案push待执行。
