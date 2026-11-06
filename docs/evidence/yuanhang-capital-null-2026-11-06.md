# 远航总股本历史 NULL 调查与续采

本次目标为调查必需金融数值缺失类型，核实固定反例的完整数据及正式归档，恢复原断点。此次完成数据恢复验证，未确认或修复来源返回 NULL 的底层原因。

## 项目、错误与初始状态

- 项目：`ths-yuanhang-financial`（远航版权息与股本历史）。
- 精确错误 ID：`a38623b4dc7a4e4a860e9ecdd18c6adf`。
- 错误时间：2026-11-06 22:38:13，北京时间。
- 反例：`300013.SZ`，字段 `402`（总股本），来源日期 `20091030`。
- 初始批次：`d846ade9d9894d56876fcf1dec583891`；`next_index/pages=1506`，累计入队 310442，revision 3012，截止 2026-11-05，待归档为 0。
- 工作区已有下载资源、成本/规划、客户端及业务文档等其他修改，全部保留。已获授权的协调聊天确认没有桌面或共享维护冲突。本轮不构建、不重启、不启动独立 MySQL、不改变任务配置。

## 分类、证据与处理边界

错误表示规范化时必需总股本数值为 NULL，校验阻止不完整单元推进断点。已有通用机制对同节点完整响应最多确认一次，并消耗原请求重试预算；再次缺值仍失败。此机制由 `c189327` 引入，本次没有新增单股特判、填零、放宽字段要求或扩大业务重试。

固定证券完整来源核实已恢复：总股本在 2009-10-30 为 60000000 股，完整联合响应有 9 条权息事件、159 个三类股本历史点，未观察到 NULL；数值字段为 kind 3/double。初次排错报告为 `build/yuanhang-financial-null-300013-probe-20261106.json`，4 次代理请求（含认证），无注册请求或业务写入。

现有证据支持“历史必需字段曾不可用、目前已恢复”，未复现解析缺陷。原错误记录的 metadata 为空、正文为空、observed_bytes 为 0，缺少当时节点和二进制字段证据；因此不能追溯是哪一个节点返回、区分源端暂时缺值与其他节点相关原因，也不能断言来源永久恢复。本次来源核实使用 node002，不能用它反推最初失败节点。

## 正式路径验证与生产进度

从真实桌面选择普通“立即采集”，确认沿用已保存配置、正式断点及恢复规则；未选择重新初始化。新运行 ID 为 `43e9254fd0ee41f49e0dde8ccefcbe40`，baseline revision 3012，与原失败断点一致。

随后使用共享 HTTP、代理与已有身份，只读取得固定证券完整来源并通过 `YuanhangDataPlugin.audit_source_proofs` 核对生产正式查询；未启动第二个归档器、未直接写 SQL。额外完整请求用于核查业务键与内容，未固化为日常双读。报告 `build/yuanhang-capital-null-production-audit-20261106.json`：

- 权息 9 条，股本 159 点；规范内容摘要、业务键摘要及归档覆盖证明全部一致，`problems=[]`。
- 正式 `capital_points` 查询返回 2009-10-30 总股本 `60000000.0000000000` 股。
- 4 次代理请求，直连/回退 0，身份注册 0，本核查业务写入 0。

2026-11-06 23:05:14 只读诊断 `build/yuanhang-capital-null-resume-20261106.json` 记录：同一 batch 的 `next_index/pages=1540`，累计入队 318952，revision 3080，已越过原反例；归档成功到该页，全局 Stream 与本项目待归档均为 0。任务状态为 running。本轮新增 34 个完整证券单元；未等待全池历史完成，不据此宣称全市场验收。Redis 与 SQL 是分别读取的时点，非原子快照。CLI 总状态 partial/exit 1 源于隔离状态没有跨进程快照及通用预览范围限制，错误、任务、断点、归档和队列 sections 正常；专用完整证券审计单独通过。

23:07:15 再次只读检查（`build/yuanhang-capital-null-final-20261106.json`）：同一批次推进到 1609，累计入队 334586，revision 3218，归档成功到 1609，全局及项目待归档仍为 0，任务继续 running；相对原失败断点增加 103 个完整单元，未出现新的 NULL 错误。此为有限恢复观察，不代表整轮完成。

## 回归与说明

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_yuanhang_history.py tests/test_yuanhang_history_client.py tests/test_yuanhang_collector.py -q --basetemp build/pytest-capital-null-300013-20261106
.\.venv\Scripts\python.exe scripts/documentation_contract.py check
```

结果：99 passed；文档覆盖与现有审阅检查通过。日志分别为 `build/yuanhang-capital-null-regression-20261106.log` 和 `build/yuanhang-capital-null-doc-check-20261106.log`。通用回归覆盖必需 NULL 分类、同节点一次确认、持续缺值失败及预算边界。本次未改变程序、正式契约、存储、用户操作或说明主题，仅登记调查证据，无需生成聚合物、重签他人审阅或重新发布；未重复全量门禁及独立库集成。

## 清理决定与未完成项

精确清理 ID：无。保留 `a38623b4dc7a4e4a860e9ecdd18c6adf`：当前数据恢复及正式归档通过，不能把一次恢复视为底层问题修复。并发新增的代理错误和既有节点故障记录未清理。未解决项是原 NULL 的节点及源端成因缺少当时证据；本轮结论为“已恢复续采，根因未复现”，不是“已永久修复”。
