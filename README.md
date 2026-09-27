# Empire

面向个人的 A 股投资研究桌面系统，使用 Python，优先支持本地 Windows。

第一阶段围绕行情与公告采集、选股和策略回测建设；当前仅提供研究和决策辅助，暂不接入券商或实盘自动下单，保留未来通过插件扩展交易能力的边界。

项目遵循“万物皆插件”：稳定内核负责启动、插件生命周期及能力契约，采集、存储、调度、分析、回测和业务页面由内部插件提供。

Windows 环境直接连接本机运行或已有的 Redis / MySQL 服务，不使用 Docker Desktop 或 WSL2。应用升级与数据库结构修改分开；需要改表时直接在现有 MySQL 中按需执行 SQL，不默认搬迁或重写历史数据。

## 当前状态

架构已确认；桌面与可靠采集管道已实现，并已接入新浪 A 股股票列表与新浪 7×24 财经新闻。其余金融渠道、选股与回测按后续阶段接入。

- [架构设计与实施阶段](docs/architecture.md)
- [需求基线、默认方案与待确定事项](docs/architecture.md#1-需求基线与设计假设)
- [Redis 到 MySQL 的归档与恢复](docs/architecture.md#6-数据管道归档与断点恢复)
- [跨插件共享采集频控](docs/architecture.md#7-跨插件共享采集频控)
- [已实现功能与验证边界](docs/implementation-status.md)
- [Windows 服务与容量配置](deploy/windows-services.md)
- [故障恢复与隔离演练](docs/recovery-runbook.md)
- [依赖与供应链治理](docs/dependency-governance-review.md)
- [独立分发与配置路径](docs/portable-distribution-review.md)
- [文档契约与稳定证据](docs/documentation-governance-review.md)
- [新浪股票列表：字段、采集与续跑](docs/sina-stock-list.md)

## 启动

动态代理采集已接入：在采集任务中按项目开启，在网站频控设置各出口和总上限，代理池页面查看在线设备及直连回退。现有任务默认直连，配置下一轮生效；详见 [动态代理采集](docs/proxy-collection.md)。

当前机器直接双击项目根目录的 `Empire` 快捷方式即可打开，不需要先执行命令。快捷方式启动无控制台窗口的打包程序：

```text
dist/Empire/Empire.exe
```

`dist/Empire` 是完整可搬移程序目录，可整体复制到带中文或空格的普通目录后直接双击其中的 `Empire.exe`。本机配置和密码不随程序复制，统一保存在 `%LOCALAPPDATA%\Empire\config.toml`；首次运行会生成空白模板并提示填写，不会自动连接或修改数据库。

开发时也可在项目目录执行：

```powershell
.\start.ps1
```

也可直接运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire run
```

代码或依赖更新后，关闭 Empire，通过正式发布门禁执行环境核对、完整测试、四档离屏布局、打包及隔离 EXE smoke；成功后同时更新根目录快捷方式：

```powershell
.\verify-release.ps1
```

`build.ps1` 是门禁内部使用的纯打包入口，也可用于已完成验证后的本地重复打包。它严格要求 Python 3.12、PyInstaller 6.22.3、一致依赖和与当前锁匹配的依赖报告，不再自动安装或容忍其他构建版本。构建身份可在“系统设置 → 运行状态”查看；`build/release-report.json` 记录 commit、工作区状态、依赖锁及依赖清单摘要、隔离容量证据、EXE SHA-256 和 smoke 结果。容量报告只使用虚拟目录和模拟响应，不访问真实代理或公开源站，详见 [隔离容量与资源稳定性验收](docs/capacity-evidence-review.md)。

桌面默认打开“工作台”，左侧一级菜单为工作台、数据浏览、采集管理、系统设置、说明文档；工作台与说明文档直接打开，其他分类通过二级菜单切换页面。采集任务管理手动执行、固定间隔、每日定时与请求重试；运行记录和网站频控分别有独立页面。启用采集插件不会自动发起采集；默认任务仅手动执行。

“采集管理 → 下载资源”支持按 100、200 至 1000 台规划出口设备一键生成容量推荐，默认 100 档为 128 下载窗口和 512 MiB 共享缓冲；也可分别设置单响应/文件大小、磁盘配额及文件并发。推荐只填容量草稿，不修改网站每 IP 频控或任务代理开关；保存到 MySQL 后正常重启软件生效，不中断当前采集。设备数不等于独立出口 IP 数，实际并发随在线出口、网站规则、预算和页数变化。详见 [下载资源边界](docs/download-resources.md) 与 [出口容量验收](docs/exit-capacity-review.md)。

股票列表页支持沪深北市场筛选、搜索、分页与复制选中行（Ctrl+C），只展示最新完整归档结果。界面操作见 [桌面使用说明](docs/desktop-guide.md)。详细说明见 [采集中心与统一管理](docs/collection-management.md)。也可关闭桌面后运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire collect-stocks
```

项目统一代码采用 `000001.SZ`、`600519.SH`、`920000.BJ` 格式，原始六位代码保持字符串类型。

本地密码位于 `%LOCALAPPDATA%\Empire\config.toml`；可以用 `EMPIRE_MYSQL_PASSWORD` 和 `EMPIRE_REDIS_PASSWORD` 环境变量覆盖。日志、单实例锁和插件启停偏好也位于 `%LOCALAPPDATA%\Empire\`，采集断点位于 Redis。旧版 `config/local.toml` 只通过 `python scripts/migrate_user_config.py` 一次性迁入，不作为运行时兼容路径。任务与网站频控配置保存到 MySQL，电脑重启后仍保留。当前版本数据库升级须正常退出后显式运行 `python scripts/migrate_collection_state.py`，详见 [统一状态维护](sql/changes/2026-09-26-collection-state.md)。

## 新环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Empire"
Copy-Item config/app.example.toml "$env:LOCALAPPDATA\Empire\config.toml"
```

编辑本地连接配置后，执行只读检查与首次建表：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire doctor
.\.venv\Scripts\python.exe -X utf8 -m empire init-db
```

`init-db` 仅在目标数据库创建缺失的 `stock`、`finance_news`、`trade_calendar` 业务表、`collection_state` 统一已归档状态表和 `app_setting` 配置表；应用启动不自动改表。已有安装通过显式维护入口升级。

## 开发入口

新增或修改采集功能先阅读 [项目协作约定](AGENTS.md) 和 [新增采集功能开发指南](docs/collector-development-guide.md)。指南集中说明插件登记、公共下载/入队/归档路径、业务专项测试和交付核对清单；不要求复制既有采集器或新增通用框架。

## 验证

```powershell
.\verify-release.ps1
```

完整门禁先核对依赖及文档契约，再使用隔离测试命名空间访问本地 Redis/MySQL，不清空共享数据、不执行结构迁移，也不会发布到外部。文档契约覆盖相对链接、正式表、配置位置、容量默认值、Redis/MySQL 持久化边界和脱敏发布基线。仅做快速开发检查时仍可分别运行 Ruff、Mypy 和目标测试，但不能把它称为发布验收。

集成测试默认跳过。需要连接已配置的服务时显式开启：

```powershell
$env:EMPIRE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
Remove-Item Env:EMPIRE_INTEGRATION
```

集成测试使用独立命名空间和随机事件身份，只清理本次测试的数据。不会清空 Redis 或业务表。

存储说明位于桌面“说明文档”，涵盖 Redis 键、MySQL `stock` / `finance_news` / `trade_calendar` 表字段和配置参数，可离线搜索。运行记录页面分为采集、归档、错误三个标签：每个项目分别保留最近 100、100、300 条，仅存 Redis，不归档。

MySQL 使用 stock 保留当前股票列表、collection_state 保留每项目一条已归档状态、finance_news 保留历史新闻、trade_calendar 保留交易与休市日期；不保存每日完整股票快照或成功 HTTP 原文。规范化业务数据进入 Redis 后立即唤醒统一归档器，60 秒周期扫描作为恢复兜底；事务提交、确认已有相同内容（含可信摘要命中）或确认消息过时后，均删除对应队列消息。失败保留重试。统一 SHA-256 摘要默认每数据集/来源最多 10000 条、7 天过期，可信缓存命中完全不访问 MySQL，缓存缺失自动回 SQL 核对，详见 [统一归档去重](docs/archive-deduplication.md)。错误原文样本只留 Redis，每条最多 64 KiB，并保存脱敏、截断和摘要信息。

错误应先修复并验证，再选中具体记录清除。清除使用精确记录 ID，不影响操作期间新产生的错误；查看页面和后续采集成功都不会自动清理。

新浪财经新闻的增量范围、断点和使用方法见 [新浪 7×24 新闻](docs/sina-news.md)。在“财经快讯”查看结果，在“采集任务”设置自动更新；新任务默认仅手动。

按最新确认，Redis 采用纯内存模式，服务或电脑重启会丢失待归档数据、断点、下次执行时间和记录；配置仍在 MySQL，启动后重建计划。只重启应用可恢复原运行状态。新闻每页 50 条，初始化仅第一页，后续接上上轮 ID 即停止翻页。所有数据插件应跳过完全相同内容的业务写入；股票无变化不替换，新闻和日历无变化不刷新观测时间。MySQL 已重启应用日志关闭配置，并已清理旧日志；redo/undo 为正常运行所需文件。维护详情见 [减少磁盘写入](sql/changes/2026-09-23-low-write.md)。

[巨潮 A 股交易日历](docs/cninfo-calendar.md) 首次补齐 1990-12-19 至下一年年底，之后维护本月至下一年 12 月，并补齐历史缺月。在“交易日历”按月查看交易、休市及未采集日期，在“采集任务”设置更新计划。命令行入口为 `python -m empire collect-calendar`。

后台按多项目规模组织：数据目录按分类/来源检索，任务列表和采集记录分页，详情独立展示，业务页面按需创建；见 [可扩展工作区](docs/scalable-workspace.md)。
