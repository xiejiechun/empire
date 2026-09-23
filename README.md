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
- [新浪股票列表：字段、采集与续跑](docs/sina-stock-list.md)

## 启动

当前机器的 `.venv` 和本地连接配置已经准备好，在项目目录执行：

```powershell
.\start.ps1
```

也可直接运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire run
```

桌面默认打开“工作台 → 总览”，导航按工作台、数据中心、采集管理、系统管理分组。采集任务管理手动执行、固定间隔、每日定时与请求重试；运行记录和网站频控分别有独立页面。启用采集插件不会自动发起采集；默认任务仅手动执行。

股票列表页支持沪深北市场筛选、搜索、分页与复制选中行（Ctrl+C），只展示最新完整归档结果。界面操作见 [桌面使用说明](docs/desktop-guide.md)。详细说明见 [采集中心与统一管理](docs/collection-management.md)。也可关闭桌面后运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire collect-stocks
```

项目统一代码采用 `000001.SZ`、`600519.SH`、`920000.BJ` 格式，原始六位代码保持字符串类型。

本地密码位于已忽略的 `config/local.toml`；可以用 `EMPIRE_MYSQL_PASSWORD` 和 `EMPIRE_REDIS_PASSWORD` 环境变量覆盖。日志、单实例锁和插件启停偏好位于 `%LOCALAPPDATA%/Empire/`，采集断点位于 Redis。

## 新环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item config/app.example.toml config/local.toml
```

编辑本地连接配置后，执行只读检查与首次建表：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire doctor
.\.venv\Scripts\python.exe -X utf8 -m empire init-db
```

`init-db` 仅在已存在的目标数据库创建缺失的 `stock`、`finance_news`、`trade_calendar` 业务表，应用启动不会自动改表。当前本机已经完成建表，无需重复执行。旧结构调整通过显式 SQL 和变更记录单独处理。依赖锁文件记录 Python 3.12 / Windows 依赖；后续依赖更新单独进行。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
```

集成测试默认跳过。需要连接已配置的服务时显式开启：

```powershell
$env:EMPIRE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
Remove-Item Env:EMPIRE_INTEGRATION
```

集成测试使用独立命名空间和随机事件身份，只清理本次测试的数据。不会清空 Redis 或业务表。

存储说明位于桌面“系统管理 → 说明文档”，涵盖 Redis 键、MySQL `stock` / `finance_news` / `trade_calendar` 表字段和配置参数，可离线搜索。运行记录页面分为采集、归档、错误三个标签：每个项目分别保留最近 100、100、300 条，仅存 Redis，不归档。

MySQL 使用 stock 保留当前股票列表、finance_news 保留历史新闻、trade_calendar 保留交易与休市日期；不保存每日完整股票快照或成功 HTTP 原文。规范化业务数据先在 Redis 等待完整性校验，每 60 秒归档；事务提交后删除对应队列消息。错误原文样本只留 Redis，每条最多 64 KiB，并保存脱敏、截断和摘要信息。

错误应先修复并验证，再选中具体记录清除。清除使用精确记录 ID，不影响操作期间新产生的错误；查看页面和后续采集成功都不会自动清理。

新浪财经新闻的增量范围、断点和使用方法见 [新浪 7×24 新闻](docs/sina-news.md)。在“财经快讯”查看结果，在“采集任务”设置自动更新；新任务默认仅手动。

按最新确认，Redis 采用纯内存模式，服务或电脑重启会丢失待归档数据、断点、执行计划和记录；只重启应用可恢复。新闻每页 50 条，初始化仅第一页，后续接上上轮 ID 即停止翻页。所有数据插件应跳过完全相同内容的业务写入；股票无变化不替换，新闻和日历无变化不刷新观测时间。MySQL 已重启应用日志关闭配置，并已清理旧日志；redo/undo 为正常运行所需文件。维护详情见 [减少磁盘写入](sql/changes/2026-09-23-low-write.md)。

[巨潮 A 股交易日历](docs/cninfo-calendar.md) 首次补齐 1990-12-19 至下一年年底，之后维护本月至下一年 12 月，并补齐历史缺月。在“交易日历”按月查看交易、休市及未采集日期，在“采集任务”设置更新计划。命令行入口为 `python -m empire collect-calendar`。
