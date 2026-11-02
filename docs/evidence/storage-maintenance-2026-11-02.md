# 2026-11-02 开发目录空间维护

用户授权按空间诊断建议清理已结束的开发产物及旧测试实例，并补充保留规则。本次没有运行采集、清空 Redis、停止 MySQL 或替换正式桌面。

## 实际结果

- 项目文件大小由诊断时约 57.17 GiB 降至 9.84 GiB；按删除清单合计移除 47.34 GiB。统计不跟随重解析点，是文件逻辑大小，不是磁盘实际分配空间。
- 通用清理选用 `--days 3 --keep-releases 3 --apply`，移除 1074 个过期产物目录、29.02 GiB。121 轮发布目录的报告、日志和证据留在原处；发布产物目录总量从约 24.01 GiB 降至 0.62 GiB。
- 显式退役 19 个停止的历史测试数据目录，另清理两个开发副本的 `.venv` 与三个旧 Qt 验证包的 `_internal`，合计 18.32 GiB。数据库仅含系统 schema 及 `empire_*_test`/`empire_test`；各父目录留下退役标记，原证据与设置文件保留，旧设置不得继续启动被退役实例。
- 单独删除 `build/architecture-e3-20261020/e2-control/build` 联接；原目标 `build` 保留。此循环是重复统计空间的来源，不能把其重复计数当实际回收量。
- 根目录配置、正式 `dist/EmpireDesktop/config.toml` 及启动器 SHA-256 核对一致。正式源码、当前依赖环境和业务数据库未参与删除。

## 运行环境核查及保留范围

运行中的 MySQL84（3306）使用 `D:/mysql/data`，MySQL_Empire（3307）使用 `E:/mysql/empire/data`，均与本次目标分离；没有强杀进程、删除锁文件或修改服务。最近的 `reuse-mysql-20261102`、`margin-mysql-20261030-v2` 等测试实例继续保留。历史源码副本、最近产物、现有正式 dist、依赖与证据仍占用约 9.84 GiB，不将这些全部视为可删除垃圾。

## 正式维护入口及验证

新增 `scripts/clean_build_artifacts.py`，默认预览、显式 `--apply` 执行；默认最近 7 天、最新 3 轮，复用发布锁与路径归属检查，拒绝联接祖先、数据库目录及活动测试/构建进程，逐项复核计划后变更。完成记录用于稳定排序，删除子目录不会使旧发布冒充最新发布。本入口为手动维护，未创建定时任务或自动启动清理。

安全回归覆盖保留规则、证据与数据库保护、变更拒绝、路径越界、Windows 循环/外部联接，以及发布锁互斥。最终 `tests/test_clean_build_artifacts.py` 为 6 passed，相关 Ruff 通过，文档审阅及 `verify_documentation.py` 通过（515 篇文档、3781 个链接、68 张表），`git diff --check` 通过。最终工具再次预览为 0 个候选、0 GiB；无需重复删除。未执行全项目测试、真实采集或桌面发布门禁，本次为开发维护工具与磁盘清理，不替换应用。

本地逐项审计位于 `build/storage-maintenance/1793594712382695000.json` 和 `build/storage-maintenance-20261102/`，包含原始清单、退役目标、执行结果与清理后统计；没有记录密码。

## 已退役的测试数据目录

- `build/architecture-evolution-20261019/mysql-data`
- `build/error-types-mysql-20261014/data`
- `build/holder-mysql/data`
- `build/index-midnight-mysql/data`
- `build/index-prices-mysql/data`
- `build/kaipanla-optimization/mysql-data`
- `build/mysql-capital-columns-20261012/data`
- `build/mysql-dividend-bulk-20261011/data`
- `build/mysql-proxy-failover-20261010/instance`
- `build/mysql-proxy-failover-20261010/data`
- `build/mysql-upgrade-20261003/mysql-drill/data`
- `build/prefetch-mysql-20261007/data`
- `build/release-main-20261019-eb2036e/mysql-data`
- `build/repurchase-mysql/data`
- `build/shareholder-mysql/data`
- `build/st-source/mysql/data`
- `build/theme-history-mysql-20261023/data`
- `build/ths-capital-mysql/data`
- `build/yuanhang-node-mysql-20261024/data`
