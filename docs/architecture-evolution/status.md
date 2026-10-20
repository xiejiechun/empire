# 模块化优化状态与下一步

事实快照：2026-10-20，E5实现提交e403faa已完成唯一正式发布（056304060b0249828b21ac2b8fafa092，committed/passed），3770 passed/5 opt-in skipped；同包配置、真实连接、正式查询、全部48设置/原偏好和真实桌面、正常关开均通过。E5组织迁移范围已验收；结案4e1dc72904925f9ba7d875f1db7e35f312c67421已push并以ls-remote精确核实。E6a七旧入口及调用方已迁移并完成正式发布与同包真实桌面（4550a9e/release 7d92659c，3773 passed/5 opt-in skipped）；48设置、原配置偏好及正常关开保持。本批组织迁移范围已验收，结案提交推送后进入E6b；后续E6b～g/F未实施。历史完整准备限制保留，整个优化未完成。接手仍先核实HEAD、工作区、远程、安装包与共享环境。见[验收手册](acceptance.md)。

交接提交120ddfc完成C发布收尾。用户已授权D→E→F实施；D八模块、安全工具、容量及两项公共UI修复已完成最终正式发布和同包真实桌面。**D纯组织迁移范围已验收，H3严格来源完整性仍FAIL**：两固定空名债券原样保留，按请求前登记、D-07及验收6.1独立判断组织等价，不称30股严格整轮通过。整个优化未完成；E0～E5已结案推送，E6a已完成同包验收，结案推送核实后下一项E6b。见[完整D记录](../evidence/architecture-d-2026-10-19.md)。

## 1. 已完成到哪里

| 阶段 | 状态 | 实际完成 | 证据 |
| --- | --- | --- | --- |
| A 发布保护 | 已验收 | 唯一发布入口、全过程所有权、输入与证据身份、暂存及可恢复切换、配置保留 | [A/B记录](../evidence/architecture-ab-2026-10-19.md) |
| B 诊断/依赖基线 | 已验收 | 有界按项目只读诊断、部分失败保留、AST债务及精确装配/顺序基线 | 同上；不能解释为所有来源均完整或全部依赖债务已消除 |
| C 新闻样板与装配 | 已验收 | features/news、Task/Bundle纯契约、显式收集、归属和六类顺序检查、旧入口退役；真实新闻、T3、完整发布、实际桌面 | [C记录](../evidence/architecture-c-2026-10-19.md)、[发布后实际证据](../evidence/architecture-c-post-release-2026-10-19.json) |
| D 持有人样板 | 已验收（组织迁移范围）；严格H3失败保留 | 八模块/旧入口退役、安全SQL及恢复、116隔离集成、两份当前容量、strict类型、最终T3 18/18；两项真实UI缺陷修复。最终发布3626 passed/5 skipped，配置/偏好/异cwd连接/三栏查询/真实启停和正常关开完成。48全代理链路一致/私有pending0；固定来源缺口不计严格实采通过 | [D记录](../evidence/architecture-d-2026-10-19.md)、[同包只读报告](../evidence/architecture-d-post-release-2026-10-19.json)、[最终证据审阅](../evidence/architecture-d-final-evidence-audit-2026-10-19.json) |
| E0 SQL归属 | 已验收；953a34e已推送核实 | 单一显式JSON及严格通用读者；最终266公共/5隔离/35文档、mypy7、T3 18/18。第二轮完整发布3660 passed/5 opt-in skipped，同包配置/真实连接/正式查询/可见桌面、启停保护/草稿/滚轮/正常关开完成；首轮文档失败保留 | [E0记录](../evidence/architecture-e0-2026-10-19.md)、[最终机器审阅](../evidence/architecture-e0-final-evidence-audit-2026-10-19.json) |
| E1 财报 | 已验收；4b30fcc已推送核实 | 十模块/资源、chain公开契约、原槽位bundle、旧入口退役；54隔离/103安全、三表40股全代理/T3通过；完整发布3669 passed/5 opt-in skipped；同包三页/帮助、依赖保护、草稿撤销、偏好恢复、异cwd连接与正式查询、正常关开完成 | [E1记录](../evidence/architecture-e1-2026-10-19.md)、[最终审阅](../evidence/architecture-e1-final-evidence-audit-2026-10-19.json) |
| E2 指数/行业/指数行情 | 已验收；b8d732d已推送核实 | 三业务包/19旧模块及调用方退役；121领域/147安全/67隔离/408公共、两轮非股票全代理链路、四份真实容量及T3 18/18；完整发布ccc04f3/release 2fa960ba、3679 passed/5 opt-in skipped；同包配置/偏好、真实连接/查询、三页/帮助、U1/U2、窄窗口及正常关开完成 | [E2记录](../evidence/architecture-e2-2026-10-20.md)、[真实桌面](../evidence/architecture-e2-desktop-2026-10-20.md)、[同包机器核验](../evidence/architecture-e2-post-release-2026-10-20.json) |
| E3 股票/日历/停复牌/准备/目录 | 已验收 | 48旧模块退役，确认注入与惰性workspace；有限全代理来源、486公共/226生命周期、T3 18/18；d062234/release 08dd70b0完整门禁3733 passed/5 opt-in skipped；同包页面/帮助/启停保护/草稿/窄窗/正常关开、48行设置及原配置偏好保持 | [E3记录](../evidence/architecture-e3-2026-10-20.md)、[真实桌面](../evidence/architecture-e3-desktop-2026-10-20.md) |
| E4 开盘啦七项 | 已验收（组织迁移范围）；严格来源失败保留 | 24旧模块退役；279领域/274公共/58隔离、当前容量/T3 18项通过；acb466a/release 61dc9811完整门禁3755 passed/5 opt-in skipped；同包七页/帮助、启停保护/草稿/窄窗/正常关开、48设置及原配置偏好保持；严格来源FAIL不冲销 | [E4记录](../evidence/architecture-e4-2026-10-20.md)、[真实桌面](../evidence/architecture-e4-desktop-2026-10-20.md) |
| E5资本事件与复权 | 已验收（组织迁移范围） | 24模块/16符号；新完整分红容量及资本管线/T3；e403faa/release 05630406完整门禁3770 passed/5 opt-in skipped；同包四页/帮助/启停保护/草稿/窄窗/正常关开及48设置/原配置偏好保持；历史准备失败保留 | [E5记录](../evidence/architecture-e5-2026-10-20.md)、[真实桌面](../evidence/architecture-e5-desktop-2026-10-20.md) |
| E6a 同花顺资本 | 已验收（组织迁移范围） | 七旧入口迁移；38股全代理5080事实、新容量及T3 18/18；4550a9e/release 7d92659c完整门禁3773 passed/5 opt-in skipped；同包全部栏目/帮助/启停/草稿/窄窗/正常关开、48设置与原配置偏好保持 | [E6a记录](../evidence/architecture-e6a-2026-10-20.md)、[真实桌面](../evidence/architecture-e6a-desktop-2026-10-20.md) |
| E6b～E6g 逐业务推广 | 草稿已准备，未合入 | E6a全部适用出口满足后继续，不应用完整E树 | [E实施](e-implementation.md) |
| F 共享治理收束 | 草稿已准备，未合入 | 仅单源文档、影响报告、类型、共享门禁、定位演练和测试成本候选 | [F实施](cdf-implementation.md)；尚无测试成本收益结论 |

不计算“完成百分比”：A/B/C与后续业务批次的工作量不同。草稿的文件数、AST相同或测试工具存在均不能折算成已完成实现。

## 2. 源码、远程和已安装包身份

当前安装为E6a release `7d92659ce1604c3a918e4317f4f7caa6`，干净实现提交`4550a9e43e3b83019ee534da472ea4dc4beef9a2`，journal committed/passed。完整输入`b5081a0161f78219b49b0ba624eca1b27d9ae49bec6f4c9654edae0ac067c740`，EXE `ff639a86d64fbd0a57c522ce899c2109247d26f60421c3c76a84399ac0667d1a`，安装树`3bbacf33f9cfc75898de24fad3e7f08afa0456ea64e725e9b3231bef29e1dba3`。3773 passed/5 opt-in skipped/20 warnings，2175.30秒，24步骤。发布后及10:02关后机器核验均exit0，同包真实栏目/帮助/启停/草稿/滚轮/914宽窄窗口与正常关开通过，48保存设置及两config/原偏好精确保留。10:03重开987020工作台可见、活动0/pending0/既有失败5。结案文档提交不改变此包冻结身份；远程待实际推送后再次核实。见[E6a记录](../evidence/architecture-e6a-2026-10-20.md)。


此前安装为E5 release `056304060b0249828b21ac2b8fafa092`、冻结干净提交 `e403faa655a4162f9a2946322a0ee25f51181ca6`。完整输入 `bcfc1b2ce7842101d52de53ebfbe9b4717648b8d48fe06a3b47932ae6473c227`，EXE `6b9ceff7ba1f78dc3fdc6925c023335047c38bb26253e85017bdcb03931b6881`，安装树 `a506088bb3e4df4a6efb7322cfeeefa9aeca12d135905c2f8c28307dfb14a27d`。3770 passed/5 opt-in skipped/20 warnings，2180.82秒；24步骤及切换通过。同包真实桌面和08:25关后机器核验通过，48设置payload/updated_at、两config及原偏好保持，重开窗口6819044工作台可见/活动0/pending0/既有失败5。详见[E5记录](../evidence/architecture-e5-2026-10-20.md)及[真实桌面](../evidence/architecture-e5-desktop-2026-10-20.md)。结案文档不改变发布身份。以下E4及更早身份均为历史。

此前安装E4正式包release `61dc981193d24b50bc84bee1c9ca1670`，冻结干净提交 `acb466aa64589400b1eea5d03abf3ee8a99a36dd`，journal committed/passed，完整门禁自然exit0。输入 `508a4fffaf9649b9d094aeae084269425d1ed34188a31cd6bbb4fb3d150f3b2a`，EXE `e6a1bd55912081d8b10846d314aedc1c9e9017aed683f4a23d8a9c66339e8a22`，安装树 `308efcdd6a3912196a0a7e535791ddde6bbaadb88224331a1e51cbb56a25ad3e`。3755 passed/5 opt-in skipped/20 warnings、2168.72秒；24步骤、容量/四DPI/打包/搬移配置smoke通过，第22步模板生成预期exit1。1528输入/54保留输出及原JUnit已机器审核。06:42关后同包异cwd真实Redis/MySQL连接、七产品正式day/完整分页和原配置/偏好核验exit0；48保存设置payload/updated_at完全相同，验收开关和草稿恢复。重开3345610可见、45任务/活动0/pending0/既有失败5。结案文档不改变包身份。详见[E4记录](../evidence/architecture-e4-2026-10-20.md)及[真实桌面](../evidence/architecture-e4-desktop-2026-10-20.md)。

以下E3与E2身份为历史：E3 release `08dd70b018394bc2bdf673bc3d8b7b99`、提交d062234、3733 passed/5 opt-in skipped；04:34同包验收通过，结案63eb8e2已推送核实，原始身份与事实见[E3记录](../evidence/architecture-e3-2026-10-20.md)。

此前安装E2正式包release `2fa960ba05f047fdbbbc6ca214b0000c`，journal committed/passed，冻结干净提交 `ccc04f399fcaa5d8815da6a1e1b17df72a541620`；完整输入 `c3f1a25884bbab7a61fb9fbbbdaafac9ff1205d170dce55eb6afbfc037cc6a32`，EXE `18f05709ca2c7855f6395c1c8c2c09f6eb58c176c699b00da38a460070a24652`，安装树 `b1eff9327f678d57a57d88c5eb322f82a23e4da69a7e370be3502329d3eff005`。完整门禁exit0，3679 passed/5 opt-in skipped/20 warnings；24步骤及打包/搬移/配置smoke通过。02:33关后同包复核exit0，配置和偏好精确保留、异cwd真实连接与正式查询通过。重开正式窗口7475560可见：45任务、活动0/pending0、既有失败5。桌面与SQL设置快照的适用限制见[E2真实桌面](../evidence/architecture-e2-desktop-2026-10-20.md)。本批结案文档不改变发布EXE身份；E2结案b8d732d已通过既有共享代理推送，ls-remote精确匹配，exit0。

以下E1身份是历史：此前安装E1正式包release `7ad607fa635c4f36b662b324dc501e52`，journal committed/passed，冻结干净提交 `a228421fa7bb312ed9fa0d7aaa0960eb2732c487`；完整输入 `f988c9bfd8e9770c455d1e6f12adfa2251a24389ffa0bd9024ecb0a12d9796e6`，EXE `40860a815a7553ad05e7a8a0551ca52b168bfcd4c129756571cfbe2808ec629b`，安装树 `0bc87e56b53c1d13de6650ec3f706f7aa5985433eefea046dac320a26df9bdcd`。完整门禁exit0，3669 passed/5 opt-in skipped/20 warnings，24步骤、容量quick/四档DPI/包和搬移配置smoke/切换通过。00:33同包关后复核及重开真实桌面通过，原config和偏好精确保留、pending0；最后窗口16058676保持工作台可见。三表实际查询及质量/公告日期限制、单停/依赖保护/草稿与正常关开见[E1记录](../evidence/architecture-e1-2026-10-19.md)。结案文档提交不改变EXE身份。远程在本次结案前核为953a34e，实际推送后再核精确HEAD。

以下E0/D/C身份与检查点是历史，不能当作当前安装包或当前待办：

此前安装E0正式包release `8ba4515618874a4dae5fbdaba42d04d7`，journal committed/passed，冻结干净提交 `99e69dba436e52eb890f407371beae6c88938274`，实现提交 `9041792f9c769b0d28d7bcbaba6fb05578666058`。完整源输入 `1ece6878aa782c16fc96e72ad43c5b8d9ee02c6ed47848ef0216242872d0c7ae`；EXE `2eb60f909c09c71109a861203fa9dbca55903e784fe9cb650f5a00e059bc4fd2`；安装树 `a772600880f929710a4bc82b632faa0a3ca12272addcab39228c15ba60683d73`。完整门禁exit0，3660 passed/5 skipped/24 warnings，四档DPI/容量/打包/中文空格搬移smoke通过；首次生成配置模板预期exit1，后续复查exit0。

22:46同包异cwd真实连接/正式查询与分页、两config/偏好精确保留、正常关闭后pending0已核。真实窗口27921844验证新帮助资源、股票/日历/新闻/三类持有人、日历UI/collector单停恢复、依赖保护、未保存草稿/滚轮。最后重开1708426可见、45任务/活动0/pending0；既有4失败和来源缺口原样呈现。偏好展开导致一次只读检查失败，精确审计后恢复原字节并新报告通过，失败保留。详情见[E0记录](../evidence/architecture-e0-2026-10-19.md)与[同包只读报告](../evidence/architecture-e0-post-release-2026-10-19.json)。这是动态快照，不能当作所有来源完整性证明。

E0结案953a34e8dc8895dd98a6a4461df212ea599c1ffc已推送main并在结案轮以ls-remote核实。本轮重新核远程遇GitHub连接超时，保留失败并在推送前重试。E1十模块/资源和调用方已迁移；239领域、187公共、103最终安全专项及54隔离归档通过；真实三表同名单30随机+10固定全代理/集合内容一致/pending0，首轮502失败保留；T3原阈值18/18通过，最终文档35专项及review/check通过，第三轮最终输入实采通过，该开发检查点现已由上列E1正式发布和桌面结果取代。

D实现提交为`ab1d47339eace79a3c9d216c23bfe6beb1b1170a`，公共帮助/滚轮修复为`7b0c69baf9ddc69e9870db177859601668c89d97`。以下D包现为历史release `de8532b2a7f146d184964805b5694b66`已committed/passed，绑定干净HEAD `b7f452adcd51da1ae61d7dde643789497dea7c45`；完整源输入`63ef47703e4f2d553f638d03585e2c01a287aa001328a763237b3527ab6ddbbd`，EXE SHA-256 `8b2a59b9592b7b8e0bfc9cf5f89d922709cbb75a8e9e8de52737e50afd1cb644`，安装树`ea9b1421cd4be510e92180bbc4b5f9eecd35773092954b2408dc764b7ed71bae`。完整门禁exit0、3626 passed/5 opt-in skipped/24 warnings；包/搬移/配置、四档DPI及发布切换通过。四条新增子进程编码警告另外重跑4 passed/无警告，详情见D记录。

最终桌面及只读复核绑定同一包。20:57正式EXE异cwd doctor两连接、三栏正式查询/分页、包树和配置/偏好保持均通过；原只读报告的actual_desktop=pending不改写，真实桌面事实在D记录独立列明。此前首轮包和17:56检查点均为历史，不能替代新包验收。最后重开正式窗口126750622可见，工作台连接正常、活动0/待归档0；这是动态快照。

本轮D结案证据提交为`08fe382677298ee4b2e650fce50cfcca0aa0b868`，main已推送；21:17再次以实际`git ls-remote origin refs/heads/main`核实远程精确匹配，exit0。此前代理核实卡住后取消，仅取消本轮Git命令；直接有界核实成功，没有更改保存的网络或Git配置。该文档提交不改变已发布D包身份。

下表保留已验收C包历史身份，不能作为当前dist身份：

| 对象 | 身份及解释 |
| --- | --- |
| 分支 | main；交接文档提交位于下列C代码提交之后 |
| C产品改造 | `2e870f1`，新闻与装配等正式实现 |
| C最终发布提交 | `81e147f35ba6af89b8b08219fe533130c875313c`，仅追加旧测试入口修复，产品代码不变 |
| C成功release | `8fbd5bd7a9cf460a9b82022b7e643f1d` |
| C完整源输入SHA-256 | `325b3eb337f2907790f7fb9d37cc83300c10d9f53fd815dc24bea2c3054e01e7` |
| 已安装程序 | `dist/Empire/Empire.exe`，窗口显示 `Empire 0.1.0 · 81e147f35ba6 · 干净提交` |
| EXE SHA-256 | `4196271f04b21eb8f987e8a000c6036dac7685dce04daab3e01bf92091926556` |
| 安装树SHA-256 | `3f010fad3279f85a5d5626a43d85b4a406afab35a643895c10ac6705b8d6e24d`，以发布专用tree_inventory算法计算 |

后续纯交接文档提交不改变已发布 EXE 的构建标识，也不冒称新包已包含文档提交。远程交付在本轮最终提交后用 `git rev-parse HEAD` 和 `git ls-remote origin refs/heads/main` 核实；之后接手仍须现场确认，不能把本文写死的旧远程SHA作为最新值。真实配置不提交Git或公共分发。

## 3. C 的实际验证与限制

- 第二轮完整门禁已结束且退出0，publication为committed/passed。全量pytest **3494 passed、5 skipped、20 warnings，2254.92秒**；5项为显式opt-in的state-unit用例，保留跳过原因，不计入通过。静态、依赖、类型、文档、装配、DPI、PyInstaller、搬移/配置/包smoke及正式切换通过。
- 首轮失败 `4a1e7b817c264d20b61f4db85352c85d`：3493通过、1失败、5跳过。失败是测试仍引用旧 `gate.builtin_catalog`，改为真实dataset contribution反例后重跑全部门禁。失败原证据保留。
- 新闻真实续采 `fresh=False`：共享代理1次、直连/回退0，1页50条，来源规范内容/业务集合与正式查询一致，成功归档且本轮待归档0。非股票粒度，30股准入不适用；不代表新闻全历史完整。
- 冻结性能9指标的median/p95合计18项全部通过，见 [C性能报告](../evidence/architecture-performance-c-2026-10-19.json)。协议与阈值未改变；不推出网站吞吐或AI效率提升。
- 发布后先后在14:31和14:36核实：程序配置、源码根配置、插件偏好均保持，安装清单/树/EXE与journal一致；在 `C:/Windows` 运行正式EXE doctor，Redis和MySQL均连接；正式股票/新闻查询可读，实际Stream待归档0。
- 正式冻结EXE在GBK与ASCII环境分别运行help、有效中文/emoji配置、缺失中文/emoji配置，共6项通过；标准输出/错误均按严格UTF-8解析，未调用业务服务。
- 真实可见桌面已观察本轮版本、服务连接和自动归档；从数据目录打开新闻与股票。股票5580条、28页、每页200条，新闻当时36194条且14:33:26正文可读。这是带时间的可用性抽验，不是实时永久总数或全源覆盖证明。
- Alt+F4正常关闭后重新枚举，Empire窗口为空；关闭后只读检查仍通过、待归档0。交接结束恢复正式窗口，后续每日任务可能继续使数据变化。

本地完整证据位于 `build/releases/<release>/`、`build/architecture-evolution-20261019/`；远程克隆没有ignored build是正常情况。已提交的C事实与脱敏发布后报告能说明本次结论；如需独立复现，按正式代码和手册重新生成新证据，不能伪造缺失的历史原日志或acceptance。

## 4. 后续必须完成的工作

| 顺序 | 待完成事项 | 开始前必须具备 | 本批退出摘要 |
| --- | --- | --- | --- |
| D | 已完成，严格来源H3失败保留 | 不重复组织迁移 | 见D记录 |
| E0 | 已完成并推送953a34e | 不重复发布 | 见E0记录 |
| E1 | 已完成同包验收，4b30fcc已推送核实 | 发布a228421、原配置偏好保持 | 不重复发布 |
| E2 | 已完成同包验收，b8d732d已推送核实 | ccc04f3/release 2fa960ba | 不重复发布 |
| E3 | 已完成同包验收，63eb8e2已推送核实 | d062234/release 08dd70b0，原preparation契约保持 | 见E3记录，不重复发布 |
| E4 | 已完成同包验收，b1418dd已推送核实 | acb466a/release 61dc9811，严格来源FAIL保留 | 见E4记录，不重复发布 |
| E5 | 已完成同包验收，结案4e1dc72已推送精确核实 | 新完整容量635期/58607来源行及原阈值通过；保留29条历史差异 | 见本批记录，不重复发布 |
| E6a | 已完成本批组织迁移范围验收 | 4550a9e/release 7d92659c，同包真实桌面完成 | 当前新容量与18项T3通过；结案提交推送核实后进入E6b |
| E6b | 上市、上市状态、北交所映射 | 精确维护发布者 | 各自业务专项；BSE完整1000行私有容量 |
| E6c | 更名、ST事件 | 各自契约与完整性 | 独立业务语义、容量及发布 |
| E6d | 解禁个股/明细、行业 | 各自正式查询与缺口规则 | 两粒度生命周期、容量及发布 |
| E6e | 业绩、股东户数变化 | 对应身份与领域公开契约 | 两类来源/存储/查询、容量及发布 |
| E6f | 股票回购 | 来源与生效范围保持 | 计划与累计回购语义、容量及发布 |
| E6g | 交易规则及剩余收尾 | remaining只含真正未迁项 | 来源规则不推断，最终所有旧入口与不当依赖退役 |
| F | 单源帮助、影响报告、类型、通用边界、定位演练、可选测试成本实验 | E各批真实退出；当前绑定齐全 | M/T全部适用项、最终全量发布、真实桌面、逐项完成报告 |

## 5. 已知缺口与不能省略的准备

1. **来源工具安全边界。** 本轮持有人验证器已合入并通过私有实例、UUID库/Redis、实际server_uuid、SQL守卫、清理/取消/恢复及真实SQL smoke。财报 `verify_ths_statements.py` 本轮已改为共享私有生命周期，随机/代理前置及观察器反例通过；真实守卫SQL smoke及三表同名单30随机+10固定已通过，首轮502失败和来源金额质量问题保留；不把管线完整等同用途通过。详见[E1记录](../evidence/architecture-e1-2026-10-19.md)。
2. **持有人来源空名债券。** `300398.SZ/2023-12-31`、`601515.SH/2024-06-30`是固定反例，不能用30只随机股票替代或换样。来源缺口可使pipeline_verified为true而acceptance_complete为false；严格来源验收必须如实失败。纯组织等价的适用判断要预先有证据，不能见失败后临时豁免。
3. **容量不能机械改hash。** D计划中的共享HTML移动将使持有人和THS资本两份报告失效。本轮已收口bindings、输入冻结/漂移反例及实际环境身份，并真实重测两报告、更新设计卡；后续按真实diff再测，旧报告保留。
4. **分红完整容量已由E5新工具和真实测量补齐。** 新协议及`measure_dividend_capacity.py`实测635期/58607来源行，原预算通过；旧只读诊断不充当该证据。29个旧键及历史完整准备失败仍保留，容量通过不冲销来源差异，见E5记录。
5. **注入是行为改造。** 股票确认服务与workspace页面工厂改成显式贡献注入，需失败、恢复、取消、清队与顺序测试；不能仅凭AST等价说完全没改行为。
6. **公共preparation不迁进业务。** `contracts/preparation.py`、`preparation_scope.py`保留唯一公共路径；仅研究/聚合实现归features/preparation，纯枚举在公共scope。禁止重建已撤销的转发方案。
7. **当前零新增债务不等于最终边界。** E要消除实际共享→业务导入，F再统一kind规则并覆盖公开API/动态字面量/债务逃逸反例；不把业务伪标platform或kernel伪标composition。
8. **实验未证明收益。** F最小schema仅opt-in候选；保留默认full、独立库、完整归属及冻结6个nodeids。未做配对测量，不声称测试提速。无收益可不采纳，保留研究事实，不影响必须完成的正式测试。

## 6. 本机资源交接

17:56曾关闭自有13348，19:25恢复调查时重新启动；D最终正式发布已自然结束。E0新核实际UUID/datadir/只有四系统库和无其他客户会话后完成隔离验证，私有实例仍运行供正式门禁。没有测试/发布/实采并行运行。D窗口126750622在E0性能前已Alt+F4正常关闭，fresh窗口列表为空；此前工作台活动0/pending0。原两份config及偏好SHA保持；E0已恢复桌面；E1曾正常关开；E2验证前窗口16058676已Alt+F4正常关闭，fresh枚举无Empire，发布和验证结束须重开。未关闭生产3307、清共享Redis或改日常网络配置。下列14:40/17:56关闭记录是历史，不能当作现在端口关闭。

程序配置、生产3307、共享Redis与RouterProxy均未因本轮文档交付改动。测试实例为本轮自有13348，数据目录 `build/architecture-evolution-20261019/mysql-data`；收尾时只读核对实际server_uuid为 `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，没有其他用户会话，只有4个系统数据库，无遗留测试业务库。14:40:33已在再次核实UUID、数据目录、无其他用户会话及仅4个系统库后执行正常SQL SHUTDOWN，并确认13348端口关闭；数据目录保留。生产3307及Redis未关闭。原证据为本地 `build/architecture-evolution-20261019/owned-mysql-shutdown.json`；不要据旧端口或PID直接SHUTDOWN。

下次如需测试，应新核实或重新建立独立实例，显式设置私有测试配置；不得借用生产3307以缩短准备。任何本地配置/ownership秘密不得提交。正式发布期间所有输入与HEAD冻结；独立worktree不隔离数据库/Redis/dist/桌面。

## 7. 接手第一步及最终完成定义

D～E5已结案推送；E6a已完成唯一正式发布、同包真实桌面及48行设置/配置/偏好恢复，结案推送核实后从E6b上市资料开始，按真实前像重基，不应用整份E候选。公共preparation契约保持原路径；持有人H3、开盘啦严格来源FAIL、停复牌精确旧错误及资本历史准备失败保留。完整分红容量已于E5真实完成，不能把容量通过解释为历史准备通过。E6a已完成本批验收，E6b～F尚未实施。以下检查点仅为历史，以文首及最终资源快照为准。

执行每批时，将该批从“草稿”推进到“正式实现→开发验证→完整发布→实际桌面→已验收”，把真实证据写入本账本对应行。任何必要项失败、缺证、运行中或被跳过，不能标完成。最终要有 [验收手册](acceptance.md) 中A/D/C/R/U/H/M/T全部适用ID的逐项结论，以及远程提交、同包发布、配置保留、真实桌面、来源限制与剩余资源说明；只有全部适用项满足才能宣布整个优化完成。

E2最新资源核查：自有13348仍运行，来源/容量私有资源全部清理；正式E1窗口已正常关闭。关闭后共享生产pending=1须保留。只读doctor tdx-suspensions退出2/status=partial：隔离状态仅存在原运行进程，CLI不能确认；已取得错误38622b7215a44fe4a5224031bdf4d963（603517在2026-10-19/20来源日期的内容冲突）。未修复、不清该ID及消息，E3按此精确ID调查；不能把partial称诊断全通过或将生产pending计入本轮私有验收。

本次恢复远程核实已恢复：有界直连git ls-remote origin refs/heads/main退出0，返回4b30fcca4e48a2fbe99e3a2729fefea38e640e2a，与本地前批HEAD精确一致。正式发布前只读preflight-final再次确认13348实际UUID/datadir/仅四系统库且无其他客户连接，config/偏好和冻结文件保持；17份当前容量报告无失效绑定。


E2历史恢复检查点：main/ccc04f399fcaa5d8815da6a1e1b17df72a541620实现已提交；release 2fa960ba05f047fdbbbc6ca214b0000c已committed/passed，替代上列历史E1安装身份。完整门禁exit0、3679 passed/5 opt-in skipped/20 warnings；配置/同包机器身份/异cwd真实连接与正式查询通过。当前窗口658542实际桌面验收进行中，未结案未推送，禁止进入E3。详情见E2记录。

E2最终资源快照02:33～02:35：正式包已正常关开、窗口7475560工作台可见/pending0；原生产pending1由正式归档处理，未手清。两config及原偏好SHA精确保留，48设置行本轮无更新（完整前像仅两行，限制见证据）。自有13348现场UUID/datadir保持，仅四系统库、无其他客户会话，无本轮私有业务资源；实例继续运行供下一批，不把历史关闭记录当当前状态。停复牌精确错误仍保留，E3调查。本段取代前述E2发布前和桌面中检查点。


E3发布前历史检查点：main/b8d732d的干净前像已核实，48旧模块及逐符号拆分已实际应用，两个公共preparation契约和三公共预览模块留原路径；股票确认和workspace惰性工厂已显式注入。第三轮84次全代理有限来源链路、私有pending0与清理通过；17现行容量绑定失效0；性能干扰已定位到本轮自有无限循环脚本并结束，稳定环境第五轮T3完整18/18通过，全部失败轮次保留。该时尚未发布和桌面；后续结果已取代该状态，见[E3实施记录](../evidence/architecture-e3-2026-10-20.md)。

E3最终资源快照04:34～04:36：release 08dd70b0已完整发布并完成同包真实桌面，窗口19336720工作台可见，活动0/pending0/既有失败5；全部48行设置内容/updated_at、两config及原偏好精确保留。自有13348现场UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、datadir保持，仅四系统库、无其他客户会话、无遗留私有业务库，实例运行供下一批。未关闭生产数据库/Redis、未删除锁、未清业务数据，停复牌精确错误未清。E4仅有忽略目录候选捕获，尚未正式应用。


E4发布前历史检查点：24旧模块及调用方已正式迁移，尚未发布/验收；58隔离集成、133安全/验证器反例通过，新七kind容量真实重测通过，旧绑定报告不改写。来源工具已替换，待实际SQL守卫smoke后再执行冻结种子20261020随机30及五固定反例；见[本批记录](../evidence/architecture-e4-2026-10-20.md)。E3结案63eb8e2已推送核实。自有13348运行，当前无测试并行；桌面已正常关闭，工作结束须重开；配置/偏好与生产数据保持。

E4最新资源快照05:38：source-verified已自然exit1，管线一致但严格来源FAIL；六项清理全true，无私有来源SQL/Redis残留。容量2实际exit0且全部私有资源清理；T3原阈值18/18通过。发布前自有13348再次核实际UUID/datadir，仅四系统库、无其他客户端；global pending0，48设置行和两config/偏好前像保存于build/architecture-e4-20261020。桌面仍正常关闭，正式发布与同包验收后须重开；本轮未清未解决生产错误、未启动E5。详见[E4当前记录](../evidence/architecture-e4-2026-10-20.md)。

E4最终资源快照06:43～06:50：release 61dc9811已完整发布并完成同包真实桌面，正常关开后3345610工作台可见、活动0/pending0/既有失败5。48行设置payload及updated_at、两config及原偏好保持。自有13348实核UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir、仅四系统库、无其他客户会话；无遗留本轮私有业务库，保持运行供下一批。旧错误/严格来源缺口未清。结案文档相关35回归及契约通过。GitHub有界直连超时保留，推送使用原共享代理；精确远程结果写本地 `build/architecture-e4-20261020/remote-close.json`，成功核实后进入E5，不将本段预写成已推送。


E5发布前历史检查点07:10：正式树已迁24模块、移16符号，精确装配及零新增债务通过。容量/配股/增发三条新安全命令均exit0，实际全代理636/1/102请求、私有pending0且六项清理true；分红29条/增发16条历史差异和准备失败仍保留，不称严格随机30通过。T3首轮17/18失败保留，完整再测18/18，阈值与工具未改。桌面已正常关闭、结束须重开；13348继续运行，所有来源私有库/前缀已清理。尚未正式发布和同包桌面，禁止推进E6a。


E5最终资源快照08:20～08:26：release 05630406已完整发布和同包桌面验收，正常关开后6819044可见、活动0/pending0/既有失败5。两config、原偏好、48行设置精确保留；13348仍运行、实际UUID与datadir不变，仅四系统库/无其他客户会话，无本轮私有资源残留。未清未解决错误或业务消息、未重启共享Redis/生产库。下一项E6a，须先核本轮实际结案提交/远程。


E6a最终资源快照10:02～10:04：同包正常关开，重开987020可见；48设置payload/updated_at、两config及原偏好保持。13348实际UUID a3e8a5eb-cb64-11f1-8ddf-380525361d4e和原datadir保持，仅四系统库、无其他客户会话、无本轮私有业务库。来源/容量六项清理通过；不关闭生产库/共享Redis、不删锁/数据/未解决错误。当前下一项为E6b，先完成本批结案提交及远程精确核实；旧发布中ACTIVE-HANDOFF已被此事实及真实desktop-checkpoint取代。
