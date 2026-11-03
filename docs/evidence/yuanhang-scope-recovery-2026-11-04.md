# 远航日线与权息股本股票池变化的显式断点恢复

## 登记与设计

用户要求继续处理上一轮续跑阻断。项目ths-yuanhang-prices；错误ID：26748de4568a41e3a12501c6374f1893、177b7968f6c749f19568392ef7ab94f1、9dac0003813b48f09edfb2f719a74222，均为未完成批次股票范围变化。只读诊断build/yuanhang-scope-recovery-doctor-20261104.json确认：断点contract2/recent，next_index1366、1365页、无半证券计划，原批次f5d68c5981e145c3aac6aa690353c58d；共享待归档为0。进一步核对同类错误：ths-yuanhang-financial的83e9680d3a274a5883fab2b7feafb07b；该任务next_index4122、4122页、批次d9ab6cc9b7dd418f83d0e6b1ecda666e，也是完整证券边界。其余旧心跳、代理、字段460及满队错误不在本次范围清理列表。

旧断点仅保存股票池摘要和位置，没有旧全池列表，因此不能根据新池沿用旧位置，也不能推断已经处理的新池前缀。原运行时拒绝是必要保护；现有显式迁移只处理旧大断点或contract1，缺少contract2范围重绑入口。

扩展唯一现有scripts/migrate_yuanhang_checkpoint.py入口，新增显式--rebind-scope和--previous-scope模式。仅接受日线/权息股本contract2近期维护、非强制全量、collecting且处于完整证券边界的断点；半证券、历史补缺及旧格式拒绝，不能据此丢弃原计划。旧名单必须有序、唯一、有界且SHA-256与原断点摘要完全匹配。正常停机、待归档为空，并经正式CollectionState.page_status确认原批次全部已入队页成功处理后，保留批次、页数、业务条数、原截止日和延期记录，将已处理前缀精确映射到新池，重置旧池跳过统计。如果新增证券穿插在已处理前缀中则拒绝，不能跳过新证券或默默重采整个前缀。后续沿原采集路径，移出证券的历史保留。

执行前独占备份原Hash及新池清单；Redis提交继续比较原cursor/revision及空队列，竞争时拒绝，不修改SQL或删除队列。不伪造完整批次完成，不把最高页码单独当完成证明，不改运行时保护或日常配置。重复对同一股票池执行无变化。

本次旧池重建证据：当前股票池5580只，日线已存年度证明5576只；差异候选仅001381.SZ、688827.SH、920085.BJ、920309.BJ。只读枚举这4项的16种成员组合，恰好一份5579只名单与两断点的1c95b4d4ebc6fa62b5e8e31af7af3bd9810ffc1344e51d02490d989321cccefb完全匹配，保存build/yuanhang-verified-previous-scope-20261104.json。当前池仅新增920309.BJ、无移出，新摘要35422a602ef9799757fb25a8a501cf68eae24c6e3f2ff0efd3a4352d3e11a823。新增位置晚于两个断点，已核对日线下一证券002906.SZ和权息下一证券603303.SH的新位置分别仍为1366/4122。维护入口只接受完整摘要证明，不把候选推断或数量相等当证明。

## 验证与执行

最终执行 tests/test_yuanhang_scope_recovery.py、tests/integration/test_yuanhang_scope_maintenance.py、tests/test_yuanhang_checkpoint.py：55 passed，26.40秒，退出码0；相关Ruff通过。专项覆盖双项目、旧池身份、已处理前缀插入拒绝、半证券拒绝及计数校验；隔离集成覆盖正式入队/归档、全部已入队页确认、零业务DML、备份、幂等、revision/队列竞争拒绝。独立13348实例确认没有私有测试库后正常SHUTDOWN，端口已关闭。

2026-11-04正常关闭Empire后，两项目dry-run均通过，待归档0。正式--apply分别成功，日线1366→1366、权息4122→4122，批次保持、业务DML为0；原Hash及新旧名单分别独占备份到build/yuanhang-prices-scope-backup-20261104.json和build/yuanhang-financial-scope-backup-20261104.json。正式回读确认新摘要、原批次、页数、业务数量与截止日保持。命令报告为build/yuanhang-{prices,financial}-scope-apply-20261104.json。

正式EXE已重新打开，在桌面分别执行普通“立即采集/按已保存配置执行”，两项目均越过原范围检查并进入计划后的节点选择；当前均被“没有已就绪且在线的远航节点身份”阻断，未推进断点。Redis TIME原子只读核对RouterProxy目录：Hash共24项，租约ZSET共1项，有效租约0；未修改目录、重新注册或切换本机身份。实际下载和后续归档尚未恢复，不能声称全历史采完；603303.SH字段460等历史问题仍保留。诊断的partial是CLI不能读取运行中进程隔离快照及该项目无自动预览，并非检查失败被忽略。

本轮只修改独立维护入口及说明，未改运行时采集器/客户端，无需重复上一轮打包与来源解析实采。最终文档聚合、审阅及文档契约通过。身份/SQL压力优化已独立提交c6c6e5c并部署，本文不重复其验收。

根据恢复代码/55项测试、生产维护回读与正式续采已越过范围检查的证据，已通过RecordsPlugin.clear_errors仅清理上述3条日线及1条权息范围错误，详见[yuanhang-scope-cleanup-2026-11-04.json](yuanhang-scope-cleanup-2026-11-04.json)。旧心跳、代理、字段460以及本轮新增离线错误全部保留。普通采集计划不变；节点需恢复有效在线租约后再续采。
