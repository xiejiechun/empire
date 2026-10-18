# 代理失败切换修复（2026-10-10）

项目：tdx-dividends（通达信分红送转）；修复共享下载器，所有调用方使用同一正式路径。

开工保留既有工作区修改；Empire 其他聊天未运行，本机桌面正常关闭，不重启数据库或修改 RouterProxy 目录。根目录和程序目录配置均为 empire:dev；开工待归档 Stream 为 0，两处配置连接下该项目错误样本均为 0。用户提供的 ProxyError 提示无法取得原错误 ID，不清理其他项目或历史记录。快照：build/proxy-failover-initial.json。

根因：代理隔离后的设备切换消耗普通请求重试预算，默认三次尝试可在其他设备或直连前终止请求。共享下载器现在按请求排除已失败设备，立即重新申请出口，设备切换不消耗来源/直连重试次数；最多 1000 个设备，并共用原总时限。无可用设备按任务策略回退直连；仅代理模式保留失败及断点。健康设备忙或等待频控仍等待。429 全站冷却、403 不轮换、正文完整性、普通重试、容量及取消释放继续执行。

未修改分红生命周期、业务键、规范化、存储、入队、摘要或归档；无需 DDL 或数据迁移。原始来源到正式查询与冷热摘要、提交后重放继续由既有资本事件集成验证；本次专项覆盖设备切换，不将模拟故障写成真实设备故障。已保存任务 use_proxy=true、proxy_fallback=true、request_retries=2，未覆盖配置。

专项结果：135 项通过，包括五设备失败后第五代理成功/全部失败直连（连接及407认证故障）、零普通重试预算仍可切换、仅代理不直连、冷却到期不重用本次失败设备、直连仍受预算限制、取消释放、跨站槽、全站冷却、正文不完整、分红来源及生命周期/恢复、预取预算。命令：`.venv/Scripts/python.exe -m pytest -q tests/test_proxy_failover.py tests/test_proxy_pool.py tests/test_http.py tests/test_cross_site_proxy.py tests/test_scale_network.py tests/test_incomplete_response.py tests/test_tdx_dividends.py tests/test_capital_lifecycle.py tests/test_capital_recovery.py tests/test_prefetch_budget.py tests/test_unit_prefetch.py --basetemp=build/pytest-proxy-failover-2`。

真实验证：09:01 北京时间，通过共享下载器按 use_proxy=true / proxy_fallback=true 请求 SH600000。普通代理路径一次请求解析 25 条；在本次独立进程内注入 7 个实际目录设备的 ProxyError 后，按设备唯一集合切换，再直连成功解析 25 条（max_retries=0）。最终来源响应是真实数据，代理故障为受控注入，不宣称这些生产设备实际故障。未写业务数据或改变采集断点，待归档为 0，共享资源全部释放。诊断使用隔离测试命名空间，7 条精确 ID 已由正式清理入口删除；未清理生产错误。详情见 [真实请求证据](proxy-failover-live-2026-10-10.json)。

正式门禁第一次因应用账号无 CREATE DATABASE 权限在隔离测试准备阶段失败；改用本次独有的 127.0.0.1:13329 临时 MySQL 实例与自有数据目录继续，不修改生产权限或服务。发布和桌面结果将在验证结束后补充；不宣称全市场分红采齐。

最终交付：共享修改稳定后，全量 1976 项通过、5 项独立 state-unit 演练按既定 opt-in 条件跳过；源码摘要保持一致。依赖、文档、数据库设计、Ruff、Mypy、容量和四种缩放比例界面检查通过。期间共享新功能的映射版本精度问题由其负责聊天修复并完成专项；本次代理修改不包含该实现。

首次打包在清理旧包 _rust.pyd 时遇到 Windows 文件锁。正常关闭后的零线程残留对象未强制终止；旧目录移到项目私有 build/locked-package-proxy-failover-20261010，保留原配置后使用 build.ps1 重建，再执行 verify-release.ps1 原文中完整的打包后门禁段。源码和已通过测试的摘要一致，不修改或伪造测试结果，不重复未受影响的全量测试。中文空格搬迁、包内界面 smoke、首次配置及复核全部通过，正式 release-report 已生成。

10:03 北京时间，正式 EXE 从 D:\ 工作目录执行 doctor 返回 0，Redis/MySQL 连通；随后恢复可见桌面，实际窗口标题 Empire · 投资研究工作台。程序配置哈希前后相同。分红断点仍为 fetch/index=2025/units=5579/collected=22917，待归档 0、项目错误 0；这是保留的实际未完成进度，未启动全市场重采，不宣称全历史采齐。原错误 ID 无法取得，生产错误未清理。自有 13329 测试实例正常 SHUTDOWN，保留私有演练文件，生产服务未重启。

发布身份、源码稳定、配置、真实窗口和最终状态见 [交付证据](proxy-failover-delivery-2026-10-10.json)。本任务实现与验证已完成，无待用户决定项。
