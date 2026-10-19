# 新闻、股东组织迁移前的本机性能基线

2026-10-19，架构演进 T3。此证据在 C/D 业务目录迁移前形成，不表示已完成迁移、全市场实采或真实桌面性能验收。

## 协议与结果

测量前登记 [固定协议](architecture-performance-protocol-2026-10-19.json)。使用首次有效完整测量形成 [冻结基线](architecture-performance-baseline-2026-10-19.json)，保留每个样本；文件以排他创建写入，没有覆盖、筛选最快样本或测后调整阈值。

- 冷进程：预热 1 次、记录 7 次；其余每项预热 3 次、记录 15 次。
- 每项 median、p95 均须 `≤ max(基线 × 1.25, 基线 + 绝对噪声底限)`；冷进程、装配、查询、UI 的底限分别为 100、2、1、5 ms。
- p95 按排序后 `(n−1)×0.95` 位置线性插值计算。比较同时检查原始样本数量、有限非负值和重新计算的统计值。
- 20,000 条固定新闻；100 只证券 × 10 期 × 3 栏目，共 3,000 份报告、36,000 名当期/退出成员。新闻存在相同发布时间，正式游标必须按新闻 ID 稳定排序。持有人夹具通过正式业务契约校验。
- 使用示例配置构造停止状态的插件管理器，经已登记 provider 执行正式查询，经 PageContribution 创建正式页面。未启动采集、归档或其他后台插件。

停止 Empire 且无同期文档校验/测试/构建后进行一次完整 [复测](architecture-performance-repeat-2026-10-19.json)，18/18 项统计阈值通过，协议、工具、机器、依赖、字体、DDL、夹具和结果内容摘要一致。

下表单位为 ms，每格为 median / p95：

| 指标 | 冻结基线 | 无并发开发负载复测 |
| --- | --- | --- |
| assembly | 1.036 / 1.301 | 1.010 / 1.314 |
| news_first | 6.184 / 7.860 | 4.917 / 6.628 |
| news_next | 1.660 / 2.723 | 1.510 / 2.279 |
| news_search | 12.039 / 14.255 | 10.799 / 12.534 |
| holders_browse | 3.387 / 4.243 | 3.131 / 3.847 |
| holders_detail | 4.489 / 4.956 | 3.265 / 3.808 |
| news_ui | 21.690 / 25.002 | 16.360 / 21.045 |
| holders_ui | 52.227 / 58.657 | 57.583 / 61.416 |
| cold_declarations | 1014.328 / 1044.793 | 917.511 / 933.461 |

## 已发现的干扰及工具修复

第一次复测时，主任务同时执行了约 5.4 秒的 `documentation_contract review` 和 `verify_documentation`，包含 CPU 工作及装配导入。该轮 [完整失败报告](architecture-performance-interference-2026-10-19.json) 保留：新闻首屏 p95 为 26.029 ms，大于上限 9.825 ms；关键词查询 median 为 15.453 ms，大于上限 15.049 ms，其余 16 项通过。已知并发负载不满足协议前提，不能用此轮调整阈值或判定目录迁移退化。

确认主任务不再运行任何命令、测试或数据库调用后，仅再执行上述一次完整复测，没有循环择优。普通系统后台服务仍存在，未停止 RouterProxyManager 等共享服务；结果只能描述本轮同机受控开发负载，不能保证每次测量零噪声。

首次有效基线之前修复了两项工具问题：Windows asyncio 的自唤醒 socketpair 先于网络守卫初始化，所有正式测量工作仍在守卫内；离屏 Qt 显式加载与正式桌面相同的 Windows 字体，检查中文/数字字形并记录字体哈希。未加载字体时的图像为方框，该轮不作为基线。修复后重新完整测量，未改变预登记的负载、重复次数或阈值。

## 安全与验证范围

- 显式设置文件只连接 `127.0.0.1:13348`；DDL 前核实 MySQL 端口、datadir 和刷盘设置。datadir 位于本工作区 `build/architecture-evolution-20261019/mysql-data`。
- 每轮仅创建 UUID 所有的 `empire_archbench_<uuid>_test` 私有 schema，使用正式三表 DDL 插入合成数据；测量期间正式查询只允许 SELECT，禁止跨 schema SQL。结束精确删除本轮 schema。
- 已通过只读检查确认前述测量的基准私库残留数为 0；最终复测也报告 `cleanup=true`。没有来源 HTTP、Redis、生产数据库读取或写入，没有覆盖日常任务配置。
- MySQL 8.4.9，buffer pool 64 MiB，`innodb_flush_log_at_trx_commit=2`。建库、灌入合成数据、字体加载不计入查询/UI 样本时间。
- `tests/test_architecture_benchmark.py`：35 passed；Ruff 通过。覆盖阈值边界、环境/协议/结果漂移、原始样本及统计篡改、NaN/Infinity、私库设置、网络守卫、基线不可覆盖及输出目录约束。
- 独立只读代码审查未发现新的 P1/P2 问题；没有并发运行审查测试影响测量。
- 对新闻及股东离屏 PNG 做过人工图像检查，中文与数字可读。离屏 QImage 不是显示器/GPU或真实桌面交互验收；冷进程也不等于冷磁盘，固定热 SQL 不代表生产全量或并发吞吐。

## 后续使用

正式 Empire 正常退出，暂停同期开发校验/测试/构建，沿用同一机器、依赖、字体、隔离 MySQL 设置和协议：

```powershell
.venv\Scripts\python.exe scripts/architecture_benchmark.py measure `
  --test-settings build/architecture-evolution-20261019/mysql-settings.json `
  --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json `
  --output build/architecture-performance-after/report.json
```

输出目录须在 `build` 内。C/D 使用正式服务和页面 ID，迁移模块路径不需要修改测量脚本；测试中的正式业务契约导入需随 D 的唯一正式路径迁移。比较会拒绝工具哈希变化，若测量实现确需修复，须另行明确新协议/基线的依据，不能悄悄重置已有基线。任何超过阈值的结果保留全部样本并说明原因，不删除离群样本。

冻结源摘要：`c82a706db8f20506cf2b5ad8ef5b93c866049e192f086de9a0bddb38286a8855`。源摘要用于证明每轮输入期间不变；前后比较允许源代码按 C/D 计划改变，并要求所有固定正确性输出一致。
