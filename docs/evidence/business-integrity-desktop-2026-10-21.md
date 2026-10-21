# 业务完整性诊断修复：同包真实桌面与资源结案

本记录来自2026-10-21约21:36～21:51的实际Windows可见操作，使用computer-use的`@oai/sky`，不是离屏smoke。唯一安装路径`D:/project/empire/dist/Empire/Empire.exe`，首次窗口33950914，正常重开后窗口6163838。本轮仅验收新增诊断及相关说明、查询、连接和正常关开，不重做A～F整轮。

## 发布与输入身份

唯一`./verify-release.ps1`实际exit0，release `e5404b467978496782a7e2fd5388dbad`，干净实现提交`df226b595c534aee58083149790cd3418709c7e3`。安装EXE SHA256 `149abf04c6934756a0e584314a6c74071c771a759c5065201bc016758455b1d2`，安装树SHA256 `04da4e90ac6f16ca11a1f884d967932a917df00c6177b61d635ec6fe743d7db0`。

`.venv/Scripts/python.exe -X utf8 build/business-integrity-20261021/audit_release.py e5404b467978496782a7e2fd5388dbad df226b595c534aee58083149790cd3418709c7e3`实际exit0，在结案文档修改之前重核1999输入、58保留输出和25步骤，见[原审计](business-integrity-release-audit-2026-10-21.json)。JUnit实际3974 passed、5 skipped、20 warnings、2556.77秒；5项均是原state-unit显式opt-in未执行，不计通过。第23步首次配置模板预期exit1，其余步骤exit0，未改写退出码。正式切换前配置保留，包内说明检查、容量和四档DPI均由原门禁执行；不将这些离屏结果算作真实桌面。

## 实际操作和观察

| 操作 | 实际结果与边界 |
| --- | --- |
| 以明确安装EXE路径启动，fresh枚举唯一窗口并激活 | 本地服务已连接；工作台45项目、活动0、既有失败5、待归档0。失败数为动态现场，不能据此认定B项已解决 |
| 说明文档搜索“历史停复牌”，打开主题并滚动到底 | 新增`metadata.conflict`说明实际可读：完整身份、两个实际来源日期、差异字段前后值；冲突拒绝入队/不推进断点；旧字段不能推测追补，一次成功不自动清旧错。正常帮助正文滚动可用 |
| 数据目录打开历史停复牌，输入603517并从候选明确选择`603517.SH 绝味食品`，应用查询；分别点击10月19日、20日 | 两日各一条同规范来源记录；来源查询日分别显示19/20日，停牌生效10-19 09:30、复牌生效10-20 09:30、说明停牌1天、原因重要公告。当前一致不证明原冲突已修复，不清原错误 |
| 打开数据准备 | 默认“长期价值研究/经营财务趋势”显示本次必需5项尚未核验，并明确“本版本发布测试已通过（不计入数据完成分母）”。本次没有运行桌面全项目详细扫描，不声称此屏已验证全部B项准备失败；相关失败来自正式只读查询JSON |
| 系统设置→运行状态 | 可见`Empire 0.1.0 · df226b595c53 · 干净提交`，缓存、持久存储、自动归档启用，待归档0。与启动路径、journal和EXE摘要共同绑定本包；未点“立即归档”绕过正常流程 |
| Alt+F4正常关闭，随后fresh枚举和进程核查 | Empire窗口为空，无Empire进程；未强杀、未删除锁。21:50:19核实退出 |
| 再次启动同一EXE，fresh选择窗口6163838并激活 | 工作台真实可见，服务已连接、45任务/活动0/既有失败5/待归档0。最终保持打开 |

上述交互未保存任务/网络配置，未切换插件开关，未向生产注入合成冲突。没有重做未受影响的U1插件启停或全部草稿组合；既有验收保留，本轮相关回归和正式门禁另列。

## 正式连接、查询、配置和消息

`installed_cli_audit.py`从`C:/Windows`运行同一安装EXE：`doctor`实际exit0、Redis/MySQL真实连接；`doctor --project tdx-suspensions --error-id 38622b7215a44fe4a5224031bdf4d963 --security 603517.SH --date 2026-10-19`实际exit2，status=partial，见[命令回执](business-integrity-installed-cli-2026-10-21.json)和[原项目JSON](business-integrity-installed-project-2026-10-21.json)。不是全部业务通过。首轮临时调用漏`.SH`被正式身份校验拒绝exit1，原`build/business-integrity-20261021/suspension-project-installed.log`保留；修正调用后重验，没有修改产品校验。

`post_release.py`分别在打开前、打开后、正常关开后执行，均exit0；[打开前](business-integrity-post-release-before-ui-2026-10-21.json)、[打开后](business-integrity-post-release-after-start-2026-10-21.json)、[最终](business-integrity-post-release-final-2026-10-21.json)核实际生产server_uuid、EXE、两config/偏好SHA256、48保存设置payload摘要，以及固定停复牌和两债券正式查询。原48设置摘要仍`63c004c25d52ff7edafb7d1b357780bd525b02353445d4f43498a3b0ce7286d5`，两config和偏好逐字节保持。

发布前原有盘口Stream消息`1792585649865-0`在打开前仍保留；新包正常归档后该消息不再待归档，全局pending0。没有手工XDEL/清空共享Redis。此项与本轮私有来源验收pending0分别记录；日常调度以后仍可产生新消息。确切停复牌旧错误`38622b7215a44fe4a5224031bdf4d963`在各次检查均存在，未补造字段、未清理。

## 资源、独立复核和剩余项

`.venv/Scripts/python.exe -X utf8 build/business-integrity-20261021/review_evidence.py`实际exit0，仅从保留JSON重算原46单元、38个1017、8单元共缺10分钟、45旧键正式可查、431月证据和三轮六项清理，见[只读审阅](business-integrity-evidence-review-2026-10-21.json)。它不是新来源验收，不改变原失败。

`.venv/Scripts/python.exe -X utf8 build/business-integrity-20261021/stop_owned_mysql.py`实际exit0，于UTC13:38:01核自有13348的UUID/datadir、仅四系统库和无其他客户端后正常SQL SHUTDOWN，实核端口关闭；[原报告](business-integrity-private-mysql-close-2026-10-21.json)。目录保留；生产3307和共享Redis未关闭、未重启、未清业务。

B4诊断缺陷已发布并完成本次适用桌面验收；B4原历史冲突、B1身份缺失、B2原46历史单元及B3历史完整准备仍按[当前账本](../business-integrity-status.md)保留失败或受限。B5当前上市状态范围检查已通过，历史用途限制不变。源码/包内资源在此结案阶段不改，不重新打包；文档检查及main远程回执另记当前账本。
