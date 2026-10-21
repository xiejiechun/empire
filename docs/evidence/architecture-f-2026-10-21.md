# F 共享治理实施与验收

当前最终状态：本批适用组织治理与帮助修复已验收。修复包280a7da/release4f8f55d0完整发布、冻结T3及同包真实桌面、配置恢复和正常关开均完成；结案提交/推送最后执行。见[真实桌面结案](architecture-f-desktop-2026-10-21.md)、[最终逐编号报告](architecture-final-2026-10-21.md)。H3/E4严格来源及历史准备失败不冲销。下文为开发与失败历史，旧“待完成”不代表当前状态。

## 前批与现场

前像为干净main `5802df660ee87914ec628ef02f425b7419fa94d3`。E6g发布`7e85c4e4db9f47bdbd5a137e731c7041`及真实桌面已验收，结案push首次传输失败、第二次成功，远程main与该完整SHA精确相同。F开工工作区无已有变更；现有修改均为本批。配置、原偏好、安装EXE、冻结文件、实际私有MySQL身份及pending=0见[现场核实](architecture-f-preflight-2026-10-21.json)。原窗口18616692工作台45任务、活动0、既有失败2、pending0；随后正常Alt+F4关闭，无活动Empire进程，交付须重开。未发跨会话消息或启动子代理。

## 修改、调用方与退役

| 修改 | 正式消费者及保持项 | 旧入口处理 |
| --- | --- | --- |
| 三项元数据精确修改 | build_info只读application/api；help_content公共parser；help_reader公共shared_ui；help页面仍business | 保留其他归属/债务/顺序，无整体policy覆盖 |
| platform→business统一规则 | 含业务公开API/contract/package和public_symbols；真实application装配与diagnostics composition例外受审；校验unused owner.kind、debt与kernel伪装 | 实际E6g仅剩shared_ui窄分支，本批替换为shared_to_business，不叠加旧分支 |
| 五个公共边界注解 | stocks/api连接内目录、calendar/api及contract、公共preparation和confirmation；调用方股票/日历审计、KPL与准备核查、各业务确认处理器保持 | 原strict8追加5为13；公共路径不搬、不加转发/ignore/cast；三解释Any与D的RawReport/RawGap保留 |
| 帮助143完整主题与来源清单 | 从最终E6g正文重新提取；23业务包本地主题、公共topics；清单仅owner/path/阅读顺序；帮助页和任务规则共用原读取/渲染路径 | storage_reference.md保留为Git跟踪生成聚合物，手工维护权威退役；运行时不生成、不回退 |
| 文档编译及review schema3 | 原read_articles保持，新增纯文本parse_articles；C静态可达/E business-schema资源及字段/主键/维护位置等原门禁保留；发布入口只check并校验包内聚合字节 | 不在门禁中generate；.gitattributes只固定帮助资源LF并纳入发布/准备摘要 |
| 保守影响报告 | 读当前architecture/assembly/preparation及静态反向闭包；公共/删除/资源/未知动态/损坏元数据扩大全量 | 报告不运行测试、不认证来源/桌面；完整发布仍全量，无第二登记表 |
| README定位和M1副本演练 | 既有各业务README的契约/关键文件/存储/生命周期/测试/指南保持，23包补本地帮助权威链接；公共preparation及通用UI位置明确 | 副本不留下正式伪业务；不复制config、私库或ownership秘密 |

未改变采集/来源解析、网络策略、消息/schema、SQL读写语义、持久化身份或用户保存设置；无DDL、启动迁移、双写、双注册或第二公共流程。原函数及类方法去注解AST相同，143主题标题/顺序及全部Article字段除实际更新的“文档分工与更新”外相同，见[类型与正文核对](architecture-f-static-audit-2026-10-21.json)。这不替代运行检查或真实桌面。

## 开发命令与实际结果

以下Python均为项目`.venv/Scripts/python.exe`；每条pytest使用独立build basetemp并写同名JUnit。输入前像、应用摘要和JUnit摘要见[开发审计](architecture-f-development-audit-2026-10-21.json)。

| 验收ID | 实际命令/范围 | 退出码与结果 | 限制 |
| --- | --- | --- | --- |
| 共享门禁/C1～C4 | `scripts/architecture_contract.py check`；pytest architecture_contract/shared_business_architecture/ui_architecture/ui_architecture_counterexamples/assembly_contract/assembly_order六文件 | 0；138 passed；最终409模块/1463导入、existing/new debt均0；精确assembly及order检查0 | 静态图不是任意反射沙箱 |
| T2/R1～R4 | `-m mypy`；`-m ruff check src tests scripts`；pytest foundation_public_api/calendar_preparation/preparation/preparation_directory/kaipanla_public_inputs/ths_holders六文件 | 0；strict13文件；101 passed | 不称全项目类型安全 |
| M2/M3/A保护 | `scripts/documentation_build.py generate`；pytest documentation_build/documentation_review/documentation_sources/documentation_contracts/storage_help/rule_documents/release_steps/packaged_runtime/release_pipeline九文件 | 首轮1：178 passed/1 failed，正式review仍旧schema尚未最终审阅；失败保留 | 最终审阅后须重跑；旧schema不能冒充通过 |
| M2/M3补充 | pytest documentation_build/documentation_sources两文件 | 0；31 passed；真实symlink拒绝及business-schema资源变化绑定通过 | 包测试为受控模拟；真正EXE待本批发布后核对 |
| T1 | pytest test_change_impact.py；三次CLI分别changed news/ui、holders/source、contracts/task，新报告不覆盖 | 最终0；45 passed；实际选择134/131文件，公共契约234全量 | 首批报告因把Qt.exec/Redis.eval误判为Python加载器而exit1，保留；修复方法区分后再测。报告没有运行这些选中测试 |
| R1～R4/E3 | 显式`EMPIRE_INTEGRATION=1`及独立13348 settings；pytest integration/test_calendar_archive.py、test_stock_archive.py、test_ths_stock_archive.py、test_news_archive.py | 0；40 passed/102.13秒 | 原每例UUID库/namespace、完整schema及全Engine guard保持，非实采 |
| M1 | `build/architecture-f-20261021/locality_drills.py --execute`；最终run75293 | 0；三副本演练通过，正式输入前后保持 | 页面为实际离屏Page，不是桌面；新增业务仅声明，无来源或SQL写入 |
| 容量 | `scripts/measure_preview_queries.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-f-20261021/preview-capacity-1.json` | 0；七kind当前样本+100000同秒点，30次原协议/阈值；六项cleanup均true | 生产只读一致性快照，写入仅独立UUID私库；固定2026-10-11为fixture版本日期，执行时间另记 |

容量报告绑定股票/日历三文件及测量工具，因实际字节改变重新实测，未刷新旧报告hash。新结果见[完整容量报告](architecture-f-preview-capacity-2026-10-21.json)，七设计卡更新引用；其余16报告未失效，最终[17份绑定审计](architecture-f-capacity-bindings-2026-10-21.json)。`verify_database_design.py`退出0，55表/49数据集/12JSON字段。

M1首轮run59d96b移除close得到真实正文为空ValueError，按要求未计通过，见[失败原报告](architecture-f-locality-first-failed-2026-10-21.json)。当前Python会整段缓冲；第二轮明确只在私有source文件把feed分为&前缀及余段并移除close，原历史函数的原content断言实际AssertionError，恢复完整源码后同一函数通过。无ImportError替代。最终[三演练报告](architecture-f-locality-2026-10-21.json)包含实际改动与一项中央白名单；手册同步解释故障注入，不声称remove-only触发断言。

F-06可选最小schema优化未采用。未执行配对实验、未测得收益，不称加速或实验通过；旧候选依赖C时期证明，持续维护成本高。正式fixture完全不改，原隔离/完整schema及正确性要求保留；以后若评估仍须冻结六例预热与四组交替实测。

最后check另发现候选CLI把相对`--report`错误交给按cwd解析的owned路径守卫；拒绝未越界。修复为显式相对项目build解析，补异cwd/父目录逃逸回归；首轮新回归暴露报告父目录未创建，保留1 failed/31 passed。补安全目录创建后两文件32 passed/exit0，`help-check-2.json`实际check通过。发布仍使用本轮绝对路径，未修改release_lock或放宽路径守卫。

## 适用边界与待完成

F未新增或实质修改采集插件，不请求真实来源，随机30股票实采不适用；继承的H3空名债券、E4严格来源及资本历史准备失败均保留，不换样、补名、清错或改写通过。E5完整分红容量已经真实完成，不由本批重复只读诊断替代。

最终文档review/schema3、check及verify_documentation均exit0（405文档/2324链接/55表）；九文件最终182 passed/59.80秒，Ruff正式范围及strict13均exit0。先前review helper缺根导入失败、Ruff误扫历史临时fixture及pytest文件名调用失败保留于[补充审计](architecture-f-development-supplement-2026-10-21.json)，未计通过。

T3按原完整命令真实运行exit0；[原始报告](architecture-f-t3-2026-10-21.json)九指标median/p95共18项全部通过、可比性差异为空、cleanup=true，源身份624fc83a0fb3c46497fb784fa839867b6df9906a18544a82653872189fd0fcc4。冷进程median1212.4878ms/p951256.19269ms，阈值1267.910125/1305.991275ms；未删样本。此前按用户指示等待外部worker自然结束，5秒CPU采样未见测试worker后测量，未发消息或关闭外部进程。冻结release_lock/性能工具/协议/基线/阈值保持。F实现提交、完整正式发布、同包真实帮助/连接/查询/配置及正常关开、结案push和最终逐项报告仍待完成。
