# O7 缺失业务契约调查：本轮证据账本

2026-10-22；仅调查和设计。交付[可行性结论、逐字段矩阵、候选设计卡和未来验收矩阵](../o7-contract-feasibility.md)。本轮没有实现O7、生产DDL、正式采集器或新发布；未做O7桌面验收。A～F不重构，O8不实施。

## 基线、现场与保留状态

开工main干净，HEAD/远程main均`8c8bd36002b4e65cfb78533a06a5d20a3a99d345`。已按序读取AGENTS/开发流程、采集指南、数据库设计规范、股东回报方案、原O7账本及27条固定样本，复用原审计，不重复全库扫描。五个调查对象和选择依据在设计中明确；001228两个编号各占一名额，未假定同事件。

[现场身份](o7-feasibility-2026-10-22/context.json)：本轮Empire PID38160，不能沿用上轮8380。EXE SHA256仍为`cc767690af7b2feb4649faaf9352de70b99f532c2bf78a1529c24302b0bac0df`，完整包树与P3 release `3892410b3e6a48858002a318bee648d5`一致；包绑定提交`6808f85188be0aae58c897b417e5819a9e6da529`。产品src/scripts/tests/sql/config/spec/发布入口相对P3提交无差异；本轮文档提交不是新发布身份。未关闭或重开应用，不操作用户桌面。

[五对象当前正式查询](o7-feasibility-2026-10-22/current.json)在UTC08:01:47～08:01:48左右读取，SQL server_uuid `77f9ba30-b666-11f1-81c5-380525361d4e`。按数据集分别RR READ ONLY事务，只查四证券完整单元（增发600590/001228/601127各4/2/4条，配股300176为1条），选中五固定键；独立正式`list_events`与SQL快照逐键逐内容相同。数据集间/SQL与Redis/后续正式查询不宣称原子快照。所有Engine有只读SQL守卫，未启动collector、调度、ingest或归档worker。

两任务checkpoint均complete；doctor的任务active=null、last_status=complete，精确队列扫描0，错误11/17条保留，归档内存隔离仍unknown。SQL状态与Redis完成观测时间不同按原可信规则解释，不据此修改证明或时间戳。doctor增发首次进程exit1但已生成完整partial JSON且终端无附加错误文本；为记录退出做一次有界重查exit2，仍仅isolation unknown。首次非零未隐藏，也未无证据称为已修复产品缺陷。配股doctor exit2/partial，亦仅isolation unknown；本轮不需启动第二归档器消除该未知。

[只读保留检查](o7-feasibility-2026-10-22/preservation.json)exit0：两份config hash与原O7审计相同，48项保存设置摘要相同；000001原范围分红0.609元/股、6.09元/10股，股息率仍已计算，分母11.44；回购五项必需准备pass，temporal非阻断fail保持。600938仍数据阻断、historical_signal仍来源受限，B4确切ID仍存在。原B1/B2/P2失败不重试、不改证据；001228未知详情键和16条历史保留记录未删除。各研究HTTP批次及只读检查pending前后均0；不承诺其他任务后续一直空闲。没有清Redis、清错误、修改生产数据或用户策略，自有13348不启动。

## 来源请求、身份与字段证据

| 实际步骤 | 证据/范围 | 结果与限制 |
| --- | --- | --- |
| 第一批，7逻辑请求 | [初始计划](o7-feasibility-2026-10-22/requests-initial.json)、[结果](o7-feasibility-2026-10-22/initial-probe.json) | TDX增发展示页、1020265/1031614详情；巨潮四证券身份检索。7 HTTP200，7代理/0直连/0回退，pending0。R1字段标签直接核实万股、网上发行日及上市日；未找到公告关联链接 |
| 第二批，5逻辑请求 | [公告计划](o7-feasibility-2026-10-22/requests-announcements.json)、[结果](o7-feasibility-2026-10-22/announcement-probe.json) | TDX配股猜测URL一次404；巨潮按证券orgId、固定原日期检索发行/配股，分别13/11/6/5公告、hasMore=false，四请求200。5代理/0直连/0回退，pending0；公告条数不证明全历史集合 |
| 第三批，4逻辑请求 | [PDF计划](o7-feasibility-2026-10-22/requests-pdf.json)、[下载元数据](o7-feasibility-2026-10-22/pdf-probe.json) | 仅下载返回adjunctUrl的四公告，HTTP200、4代理、0直连/回退，pending0。总计16逻辑/16实际代理，停止请求，未启用第三来源路径 |
| PDF核读 | [有界原文摘录](o7-feasibility-2026-10-22/excerpts.json)、[600590表格局部](o7-feasibility-2026-10-22/600590-p17-table.png)、[601127含脚注表格局部](o7-feasibility-2026-10-22/601127-p9-table.png) | pypdf提取并用Poppler渲染核对表头、列、股数及脚注。600590 p17无限售后列原文逗号分组作`50,2005,712`，保留原样，不改源文；正例用清晰的股份总数及本次变动行。渲染有本机替代字体警告，图像表头和数值可读；不将文本提取自动正确当作未来解析器已验收 |

| 公告及官方URL | 本轮文件身份、关键位置 | 结论 |
| --- | --- | --- |
| [600590 /1202003671](https://static.cninfo.com.cn/finalpage/2016-02-27/1202003671.PDF) | 573989字节/19页，SHA256 `898d485244ba9d2e63a8cc4f4da635e71a9006f2ffd21782b5b8d06140fe568c`；p1/p6/p15～17 | A，公告购买资产发行段可复核；精确字段、归因边界和TDX候选关联限制见设计 |
| [300176 /1225530947](https://static.cninfo.com.cn/finalpage/2026-08-28/1225530947.PDF) | 314043字节/11页，SHA256 `dbf90445a9712175f7aeebf6b2865a0a0b176c97ad4969d84ea6d37b7bb8379b`；p3～6 | B，实际数量/股本表充分，精确登记日期缺失，不用除权/上市日替代 |
| [001228 /1225587665](https://static.cninfo.com.cn/finalpage/2026-09-30/1225587665.PDF) | 1347291字节/31页，SHA256 `7c43ca9ce156a46f2e5e3ac86d57af1cfcb01e001d848708e5ab78bab4c9f2aa`；p9～12/p16～17 | B，同一公告研究两个编号的候选关系；受理非登记完成，不消除1043980未知详情，不自动去重 |
| [601127 /1210364916](https://static.cninfo.com.cn/finalpage/2021-06-30/1210364916.PDF) | 601663字节/12页，SHA256 `913790af5b15a49c145f4b0f3a9aea2beaa48f70bdf286135938c4f92e37e5b9`；p1～3/p9～10 | B，明确实施和并发转股说明；63股差不是任意舍入，但未取逐次转股身份，单事件归因仍阻断 |

PDF观测UTC07:58:35～07:58:37（北京时间15:58）。公告当年公布日不是本轮取得证据时间；索引announcementTime的日内语义未核实，不能冒称historical_signal可用日。没有保存完整PDF/全文到Git、MySQL或Redis业务队列；URL/hash/页码与有限摘录供复核，本轮不是新增公告存储。

## 实际命令与退出

工作目录`D:/project/empire`。研究工具在build路径执行，Python `.venv/Scripts/python.exe -X utf8`。归档工具仅供审计，复现时复制回`build/o7-feasibility-20261022/`；三个requests计划按批复制为requests.json，输出使用新文件名，不能把静态JSON当新执行结果。

| 命令 | 退出码/证据含义 |
| --- | --- |
| `python -X utf8 build/o7-feasibility-20261022/probe.py initial-probe.json` | 0；网络政策、逐次路由/时间、字段快照和正文hash见初始结果 |
| 同脚本`announcement-probe.json` | 0；单项404仍保留为失败，不将脚本退出0写成全部来源成功 |
| 同脚本`pdf-probe.json` | 0；四文件签名及身份、共享下载实际路由 |
| `python -X utf8 build/o7-feasibility-20261022/extract.py` | 0；有界摘录，全文只留临时目录，不是生产解析器 |
| `pdftoppm -f 17 -l 17 -scale-to 1400 -png -singlefile <600590临时PDF> <临时输出>`；同法601127 p9、300176 p5 | 三次0；仅用于人工布局/列核对，字体警告如上，不是新业务验收 |
| `python -X utf8 build/o7-feasibility-20261022/preservation.py`、`context.py`、`current.py` | 各0；前两者复用上轮工具作本轮新读取，current限制五对象，不作全表新审计 |
| `python -X utf8 -m empire doctor --project tdx-additional-issues --security 600590.SH --date 2016-02-18 --output build/o7-feasibility-20261022/doctor-additional.json` | 首次1/partial原件保留；仅一次重查2/partial，见[实测命令](o7-feasibility-2026-10-22/doctor-repeat-command.json)及独立JSON，未启动来源请求 |
| 同doctor，project=`tdx-rights-issues`，security=`300176.SZ`，date=`2026-08-21` | 2/partial，见[实测命令](o7-feasibility-2026-10-22/doctor-command.json)；隔离unknown保持 |

[原件清单](o7-feasibility-2026-10-22/inventory.json)记录白名单文件字节及SHA256；先设置本目录保留原字节属性，再入Git并逐项核对索引blob，不复制config、原始凭据、完整正文或其他发布工作区。最终文档审阅和相关文档回归在设计/证据归档后执行，实际命令退出另存，不复用上轮63通过当本轮结果。

当前恢复点：调查和设计完成，等待审阅有限A范围/成本/存储候选。正式数据契约、采集实现、容量/数据库准入、30股实采、O7计算/页面、发布及桌面均为未来实施项目，当前不标已验收。保留所有原失败，不能把本轮600590正例扩大为全证券历史可用或O8已具备输入。

文档检查实际结果：generate/review/verify均exit0，423文档/3556链接/55张现行表；五文件文档回归63 passed、60.31秒、exit0，`git diff --check` exit0。见[逐命令实际退出记录](o7-feasibility-2026-10-22/documentation-checks.json)、[JUnit](o7-feasibility-2026-10-22/documentation.xml)及同目录日志。63项是文档相关回归，不是O7产品验收；未重跑发布门禁，也未以旧包做新功能桌面。追加本段结果后再执行最终显式审阅、契约及当前文档契约回归，原始退出另存final-checks.json；提交推送后核对远程main，不把文档提交当新包。
