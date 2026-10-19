# E3 股票、日历、停复牌、准备与目录实施记录

状态：开发验证通过，尚未发布或完成桌面验收；不得进入E4。前批E2结案 `b8d732d4f44420c5711c3fdfa8ba6a46e418c9f7` 已推送核实（本地 `build/architecture-e2-20261020/remote-close.json`），安装包仍为E2 release `2fa960ba05f047fdbbbc6ca214b0000c`。

## 输入、范围与退役

开工main/b8d732d、工作区干净。只读核实安装EXE与E2 journal、两config/偏好及冻结工具摘要；自有13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、独占数据目录、仅四系统库、无其他客户会话，区别于生产实例。共享pending=0。未发现并行发布/测试/维护；正常Alt+F4等待活动采集退出后，fresh窗口枚举无Empire。没有强杀数据库、删锁或清共享Redis。

本批按计划登记的E3迁移48旧模块到 `features/stocks`、`calendar`、`suspensions`、`preparation`、`data_browser`，逐符号拆分审计、目录证明、发布标记和日期契约，调用方、测试patch、规则登记、coverage和装配同步；旧文件删除，无转发。候选仅提取本批路径，未来业务导入回到当前正式路径；保留E1/E2已验收修改。实际字节前像、暂存、SHA拒绝漂移应用记录在本地 `build/architecture-e3-20261020/`。48模块及拆分定义在去除导入/文档串并映射名称后AST比较无业务表达式差异；这不是运行通过证明。

`contracts/preparation.py`、`contracts/preparation_scope.py` 保留公共唯一权威，研究选项原值进入公共scope；公共预览cards/navigation/layout保留原路径并按实际职责登记shared_ui。无DDL、消息schema、物理键、插件/任务/页面身份或用户保存设置变化。股票确认完整业务体成为无状态回调，bundle/dataset明确提供/需要 `stocks.snapshot`，bootstrap在原7200槽注入。workspace在原14800槽由data_browser贡献惰性页面工厂，后置preparation装配保持原顺序。

共享UI反向业务导入检查和反例本批实施；全局运行时通用边界依赖E4的schema入口泛化，仍按后续手册完成，不将它冒称本批已实现。未提前改变E4正式实现。

## 适用验收与当前证据

| 验收ID | 实际命令/证据与结果 | 限制及剩余工作 |
| --- | --- | --- |
| C1/C2 | assembly_contract check，原semantic和六类顺序精确映射，exit0 | 正式发布仍待执行 |
| C3/C4 | architecture-4.json：365模块/1379导入、31既有/0新增/16退役，exit0；mypy7文件exit0；ruff exit0 | 不宣称全部架构债务已消除或全项目strict |
| E3/R1/R2 | domain-3.xml，229 passed/17.24秒/exit0 | 最终改动后仍须汇总复核 |
| R1/R3/R4 | 四类归档隔离integration.xml，31 passed/76.68秒/exit0 | 公共调度/队列/页面回归须最终执行 |
| 注入与安全 | source-safety-final.xml，135 passed/2.09秒/exit0；boundary-4.xml，71 passed/19.44秒/exit0 | 含真实回调SQL/Redis失败与取消传播、marker回源、精确惰性页面身份；不替代SQL恢复或可见桌面 |
| 实际来源 | 新 `verify_foundation_sources.py` 复用已验收私有生命周期；第三轮foundation-source-3.json已通过，exit0 | 双源完整目录、限定整月和固定停复牌日期；均非逐股票请求，不声称随机30股通过 |
| 容量 | 最终扫描17份现行measured报告，绑定失效0，capacity-impact-final.json | 原数字与hash保持，不需要本批容量重测 |
| T3 | 第五轮完整18/18通过，exit0；[实际报告](architecture-performance-e3-2026-10-20-5.json) | 所有原样本保留；前四轮失败/两个E2对照和环境恢复证据一并归档 |
| M/文档 | 正文、README、coverage、结构说明同步中 | 最后review/check与文档回归尚未完成 |
| U1/U2/U3 | 未执行 | 完整正式发布、同包连接/查询/桌面、配置偏好保留与正常关开均待完成 |

实际pytest命令均使用 `.venv/Scripts/python.exe -m pytest -q --tb=short`，指定独占 `build/pytest-e3-*` basetemp及上列JUnit路径。隔离显式启用 `EMPIRE_INTEGRATION=1` 与自有13348配置。未运行或失败不合并进passed。

首轮领域失败为拆分后calendar patch仍指向通用evidence，修正到calendar.audit_rules。公共回归发现另一个suspensions.audit patch和catalog绝对引用遗漏，已修；新共享UI检查还发现公共控件旧metadata仍为业务，已按真实职责修正。过早提取的全局运行时规则依赖E4，在候选中撤回；不添加债务豁免或改性能阈值消除失败。原日志/JUnit保留。手册中的foundation_public_api测试原不存在，本批从已审候选重建实际连接/动态映射反例后执行。

## 精确错误与资源

项目 `tdx-suspensions`、错误 `38622b7215a44fe4a5224031bdf4d963`：603517.SH于2026-10-19/20来源日同身份内容冲突。已先登记并有界只读doctor读取错误正文及正式查询，报告status=partial（CLI无进程内隔离证据），不能称完全诊断通过。未做来源语义修复、未清此ID；两轮固定近期日期只读来源复核未复现旧冲突。该近期范围没有在空库伪造历史覆盖进行归档。D两固定空名债券的严格H3失败及E5分红完整容量待办原样保留。

桌面为本轮验证正常关闭，自有13348仍运行；配置、生产业务数据、共享Redis和日常代理策略保持。每次真实验证仅使用有实际UUID与owner守卫的独占库/namespace，归档成功清队由公共归档器执行，清理成功后才能判通过。后续恢复先检查本轮进程、ownership报告和资源状态，不能猜测删除。

## 有限实际来源结果

第三轮命令：`.venv/Scripts/python.exe scripts/verify_foundation_sources.py --pool-config config.toml --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output build/architecture-e3-20261020/foundation-source-3.json`，exit0。输入身份 `59bea7e1b334f6d8dfe8bd87c1239181ed71051efdf64d230b6378cd5cfb5f99`。新浪5574只/73请求，同花顺5579只/1请求；日历1990-12、2026-10、2027-12分别13/31/31日、3请求；停复牌2004-12-27～31来源起点连续五日15/57/37/36/39条，加近期固定两日只读复核，共7请求。84请求全部代理，direct/fallback=0；每项正式管线、查询集合与内容一致，本轮pending=0，errors空，六项cleanup均true，remaining sql/redis均false。非逐股票接口，随机30股门槛不适用；有限日期不代表全部历史覆盖。

首轮验证器错误地从近期日期起采，空库缺来源起点连续覆盖而被归档拒绝，取消后没有形成最终报告；通过正式cleanup-only恢复，foundation-source-1-recovery.json exit0并核实资源清理，不能将中断轮记通过。第二轮股票/日历通过，停复牌因SQL秒精度与来源分钟精度直接字符串比较失败；六项清理成功。补时间表示等价及内容变化拒绝反例后第三轮通过。全部失败原始报告保留，不改写其结论。

## 最终验证与性能故障处理

最终公共/领域/UI汇总final-2.xml（486 passed/47.49秒/exit0）、公共生命周期lifecycle-final-2.xml（226 passed）、装配/文档common-final-2.xml（70 passed）对应当前正式树。首轮汇总485 passed/1 failed，为九条历史审计链接指向已退役文件；现将链接固定到前批b8d732d的历史文件，审计事实不改。公共预取首轮6失败为两个动态模块名遗漏，已同步测试调用方并复验；不复活旧模块。误用不存在的测试路径两次均未运行，不计通过。

前两轮T3失败后同机E2对照也有冷启动超限。第一轮E2归档副本因换行字节导致冻结身份不符，明确不可比；恢复原始前像和未改文件字节，核src/sql与E2 Git内容后第二轮可比、仍有冷启动超限。进一步核实早前本轮一次性元数据脚本在遍历module_groups时追加匹配项，形成无限循环，PID52248占用103791964160字节工作集/144475344896字节私有内存。已核父脚本正文、进程关系及开始时间，只终止该本轮失控Python；脚本不访问数据库、未到写文件语句，没有强杀数据库或清共享资源。其后架构精确复验通过。

第三/四轮内存继续回收，分别剩新闻搜索/新闻首屏p95单项超限，原样本全部保留。预登记恢复条件为连续三次可用内存>=100GiB且总CPU<10%；首次条件未满足，未启动测量；第二次末三样本9/7/9%、可用内存约105GiB，条件满足后完整第五轮18/18通过、incomparable空、cleanup成功。没有删慢样本、改基线/阈值/工具或取各轮最快指标拼接。具体记录见[干扰归属](architecture-e3-performance-interference-2026-10-20.json)、两份environment-recovery与全部performance-e3报告。此为本机冻结合成负载，不代表来源吞吐或真实桌面。

Redis构造登记逐项比对只有两表达式归属变化：stocks:committed与stocks:result由公共provider迁入业务confirmation，self.redis参数化为redis；原物理键、类型、TTL和清理语义不变。逐对象sources同步到实际确认读方；publication只负责解析，不新增物理键所有者。未盲目刷新全扫描。最终逐功能文档审阅保留用户正文，具体不变理由与受影响源逐项记录；五包README及业务/结构正文同步。


发布前只读[证据审阅](architecture-e3-pre-release-audit-2026-10-20.json)通过：逐JUnit核计数/失败/跳过，按原始样本重算18项T3，核源/配置/冻结工具、48旧路径退役及17容量绑定。来源实测后仅新增公共预取测试的两条动态模块映射；[精确身份桥接](architecture-e3-source-identity-bridge-2026-10-20.json)以该单文件前像重构出原实采摘要，其他所有源码、验证工具、SQL和配置字节完全相同，原实采报告不改hash；该测试226项复验通过。最终八项静态/类型/装配/架构/文档/设计命令均exit0。远程直连核实失败exit128；已保存的origin/main仍b8d732d，后续推送使用既有RouterProxy并精确核远程，不修改日常或Git保存配置。

正式发布与同包真实桌面仍未执行，不将开发验证等同阶段验收；下一步冻结实现提交及受保护输入，运行唯一verify-release.ps1。工作区全部改动均为本轮E3，未混入其他任务文件。
