# P3-28 独立分发与配置路径验收

日期：2026-09-27。

## 正式路径

打包后的 `Empire` 目录是完整程序目录，可以整体复制到普通账户可读的任意 Windows 目录。程序不再通过 `Empire.exe` 的父目录猜测仓库根目录，也不从当前工作目录读取资源：Qt 图标、空白配置模板、SQL 初始结构和内置说明均随制品放入只读资源目录，运行时通过 PyInstaller 资源根定位。

本机可写状态统一位于 `%LOCALAPPDATA%\Empire`：

- `config.toml`：Redis、MySQL、本机下载目录等机器配置；
- `downloads`：未显式配置时的文件下载目录；
- `empire.log`、`empire.lock`、插件状态：日志、单实例锁和本机界面/插件状态。

程序目录不写配置，不包含真实账号密码。`--config <绝对或相对路径>` 仍是显式维护、恢复演练和隔离环境的正式覆盖入口；未指定时只有上述一个默认位置。相对 `http.download_directory` 以配置文件所在目录解析，不再受快捷方式“起始位置”影响。

## 首次运行与迁移

默认配置不存在时，Empire 从随包空白模板创建 `%LOCALAPPDATA%\Empire\config.toml`，随后停止启动并明确要求填写连接信息。双击无控制台版时以窗口显示错误；不会用空白默认值连接服务、创建表或自动迁移数据库。编辑完成后再次打开即可。

旧版仓库内 `config/local.toml` 不再作为运行时兼容搜索路径。已有安装只执行一次显式迁移：

```powershell
.\.venv\Scripts\python.exe scripts\migrate_user_config.py
```

维护入口默认从旧位置复制到用户目录；目标已有相同内容时幂等成功，已有不同内容时拒绝覆盖。它不打印配置内容、不删除旧文件，也不连接 Redis/MySQL。确认新版正常启动后，旧文件仅作为用户自行管理的历史副本，不再被运行时读取。

配置语法可在不连接 Redis/MySQL 的情况下检查：

```powershell
dist\Empire\Empire.exe check-config
dist\Empire\Empire.exe --config D:\isolated\config.toml check-config
```

## 自动验收

发布门禁在打包后把整个程序目录移动到 `build` 下带中文和空格的临时层级，以该目录作为工作目录执行 EXE smoke。随后使用隔离的 `LOCALAPPDATA` 验证：首次启动创建空白用户配置并以退出码 1 提示；第二次 `check-config` 成功；制品包含模板、SQL 和依赖清单。验证结束后程序目录原样移回 `dist/Empire` 并清理门禁自己的临时目录。

单元测试另覆盖资源根不依赖 EXE 父目录、首次配置只创建一次、相对下载目录稳定解析，以及旧配置迁移不覆盖不同目标。该验收证明目录可搬移和启动寻址正确；它不是安装器、代码签名或跨机器 Redis/MySQL 连通性证明。

