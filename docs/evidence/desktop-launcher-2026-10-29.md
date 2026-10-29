# 新版桌面双击启动器验收

2026-10-29：交付dist/EmpireDesktop/Empire.exe，为Windows GUI子系统x64本机启动器。依赖项目desktop/node_modules中的Electron、desktop/dist前端资源以及.venv Python环境，不能作为独立程序搬到其他电脑。

配置从用户指定的dist/Empire/config.toml逐字节复制到启动器同目录，使用显式绝对--config传递。不同的既有目标配置拒绝覆盖；未输出配置正文。原dist/Empire/Empire.exe和设计预览保留。

构建持有原ReleaseLock，正常关闭旧客户端后执行前端构建、协议/启动参数测试及C# GUI EXE编译；冻结启动器/前端输入，PE子系统核验为GUI。未声称通过独立程序完整发布门禁。

实际启动工作目录为C:/Windows，启动器成功打开新版可见桌面，读取47个未归档任务与真实运行记录；使用computer-use观察窗口并点击“正常退出”，再重新启动。未发起手动采集、计划保存或记录清理；原Runtime仍按已有计划工作。

复现：.venv/Scripts/python.exe scripts/build_desktop_launcher.py --config-source dist/Empire/config.toml。测试：npm --prefix desktop run test:transport。操作说明见desktop/README.md。
