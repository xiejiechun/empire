# 采集任务 Shift 多选与批量启停

## 范围与工作区

入口：采集管理 → 采集任务。目标为 Shift 连续选择具体项目后批量启动、停止；同时支持 Ctrl 增减选择。工作区已有大量未提交修改，本次保留，未将其他任务的改动提交或清理。开工查看聊天与进程，其他 Empire 聊天未在执行；正常关闭原桌面进程，未强杀程序或数据库。

本次不是根据错误样本修复，不涉及错误记录 ID 或清理。未新增或实质修改采集插件、来源请求、业务数据集、SQL 结构或入队归档路径，因此来源实采、生命周期及数据库迁移准入不适用；没有以本次 UI 测试替代来源完整性验收。

## 实现与边界

- TaskMenu 使用 Qt ExtendedSelection，支持 Shift 连选和 Ctrl 多选；来源节点不计入任务。稳定刷新不改动 Qt 选择模型，筛选重建后按任务 ID 保留仍存在的选择，隐藏项不参与命令。
- 列表下方提供独立批量按钮及已选数量，来源节点被设为当前项时也可操作已选具体任务。单任务详情、编辑草稿和原单任务操作继续按当前任务管理。
- CollectionControl.batch 逐项复用 configure/run/pause，ID 去重；已归档跳过，运行中启动跳过。启动启用所选任务并保存，使用各自已保存设置续采，不使用 fresh；停止保存禁用状态、关闭后续计划并保留断点和业务数据。
- 单项失败继续处理后续项，显示成功、跳过、失败数量；最多预览三项简短异常，完整逐项结果放在悬停提示。已启用后启动失败会明确标注，避免误以为任务仍停用。
- 使用公共 action Future，操作期间锁住按钮，页面查询销毁不取消已提交写命令。未增加数据库或 Redis 路径。
- 更新程序内“执行采集与计划”、app_setting 与 collection-control 参考、管理与桌面指南、实现状态。现有 documentation-coverage.json 已将 collection 页面关联到上述操作主题，无新增页面，关联仍有效；按功能记录文档审阅。

## 验证

- 最终专项：`python -m pytest tests/test_task_batch_ui.py tests/test_collection_ui.py tests/test_collection_control.py -q --tb=short --basetemp=build/pytest-task-batch-final2`，90 passed。
- Shift 鼠标连选、Ctrl 增减、刷新保留、筛选去除隐藏任务、草稿保留、提交时按钮禁用、批量停止目标、部分失败结果及43项长错误的有界显示均有回归。
- 控制回归覆盖暂停后批量启动并保存启用、去重、未知任务失败后继续、运行中跳过、批量停止并清除计划、归档任务跳过；没有真实网络请求。
- 独立数据库的配置与隔离探测：3 passed。使用原有 build/index-prices-mysql/settings.json 指向13331测试实例，不提升业务账号权限，不重启3307或共享Redis。
- 全量集成测试过程中核对13331端口和测试datadir后，将独立实例的运行期 innodb_flush_log_at_trx_commit 从1设为2，以减少事务刷盘等待；未持久写入服务配置，生产不变。测试仍校验正常事务及应用进程中断重放，本次不以它证明MySQL服务/主机崩溃后的持久性；参数留痕 build/task-batch-test-db-tuning.json，收尾恢复并正常关闭测试实例。
- 离屏模拟截图：build/task-batch-1320.png、build/task-batch-880.png。已目视检查，属于模拟布局证据。
- 文档契约182主题、1256链接、55表通过。最终全量测试2632 passed、5 skipped、2 warnings，用时37分52秒；跳过均为 tests/integration/test_state_unit_isolated.py 的显式演练开关，不是为本功能新增跳过。quick容量与1/1.25/1.5/2四档DPI均通过。完整发布日志 build/task-batch-release-final.log；统一发布门禁最终通过，含打包、中文空格目录便携检查、首次配置准备、配置复核及package smoke。构建身份和EXE摘要见 build/release-report.json。

## 失败留痕与桌面限制

首次专项的新测试样本缺少 history 字段，补齐样本后90项通过。首次完整门禁未指定独立MySQL，业务账号没有创建测试库权限，中断后改用现有隔离实例；没有放宽测试或提升业务账号权限。隔离门禁中间为修正长错误布局主动停止一次，最终源码复验并重新审阅后完整重跑。

computer-use 技能初始化后，sky.list_windows 连续两次返回 native pipe unavailable，系统找不到指定文件；按技能恢复边界停止桌面输入。因此尚未完成真实桌面 Shift 点击与批量操作验收，离屏回归不冒充真实桌面验收。

## 最终程序与收尾

2026-10-16 13:09北京时间完成最终核验：dist/Empire/config.toml 的SHA256与正常关闭前一致，未输出凭据；新EXE从 C:\Windows 运行 check-config 和只读 doctor 均返回0，证明配置按程序目录定位，Redis/MySQL均连通。随后从同一工作目录打开正式桌面，确认进程31356的可见主窗口标题为“Empire · 投资研究工作台”；这只是窗口存在证据，不替代真实Shift点击验收。检查结果保存在 build/task-batch-program-verification.json。

独立13331测试实例的刷盘参数已恢复为1，核实datadir与无其他连接后发出正常SHUTDOWN。关闭连接时的回滚因服务已退出出现2013断连；日志明确记录Normal shutdown及Shutdown complete，端口连接复核已关闭。共享Redis、3307生产MySQL及其他MySQL服务未重启，未删除业务数据、待归档消息或错误记录。

当前交付边界：批量功能、专项与正式发布完成；唯一未完成验收项为桌面工具不可用导致的真实鼠标点击验证，无新增实采完整性结论。
