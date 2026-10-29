# 新版桌面同花顺采集立即失败修复（2026-10-29）

## 定位与修改

用户反馈能启动但迅速失败或无进度。真实 Redis 记录及桌面显示共同确认 ths-capital 两轮、ths-holders 一轮在首次请求前失败，错误为“同花顺请求校验需要已初始化的 Qt 应用”。具体运行 ID、错误 ID 见 desktop-qt-runtime-errors-2026-10-29.json。

旧 GUI 和原 CLI 创建 Qt 应用；新 desktop_bridge 入口只创建 Runtime，遗漏了同花顺 QJSEngine 的进程依赖。修复仅在新入口的主线程创建 QCoreApplication 并持有至 Runtime 线程退出。不修改采集解析、下载、代理、断点、归档、业务结构或用户计划。不创建 Qt 窗口。

## 验证范围

- 新增独立子进程启动回归，通过实际 desktop_bridge.main 入口，在后台线程调用 ThsSession 和 ThsDirectorySession 的真实本地校验脚本；检查 Runtime 启动与退出时 Qt 实例均存在。没有使用测试进程预先创建的 QApplication 掩盖启动遗漏。
- 真实源码入口启动 Runtime，在其线程调用两个原采集器 fetch，固定首次失败证券 000001.SZ，各一个完整响应；资本运作全栏目及股东研究三栏解析成功，各 1 次共享代理请求，无直连/回退。详见 desktop-qt-source-smoke-2026-10-29.json。
- 本次是共同启动依赖修复，没有实质修改采集器；一证券足以复现此前零请求即失败的反例，未为凑比例扩采。总体股票池 5579，本次每入口 1 证券。不是全市场验收，也不是本轮完整入队→归档→正式查询验收；此检查不手动发布业务消息。启动原 Runtime 仍会恢复已保存自动计划。
- 精确清理已记录且验证修复的 3 条错误；再次读取确认不存在，保留其他错误及所有历史运行记录。
- 使用共享构建锁重建本机启动器，保留原配置、旧客户端和设计预览。该启动器依赖源码 Python 环境，不代表独立正式包发布。

相关回归最终结果：tests/test_desktop_bridge_startup.py、test_desktop_bridge.py、test_collection_control.py、test_ths_capital.py、test_ths_holders.py 共 601 passed。文档审阅与契约检查通过。验证后从 C:/Windows 工作目录重新打开 dist/EmpireDesktop/Empire.exe。
