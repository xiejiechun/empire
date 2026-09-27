# Empire 故障恢复与隔离演练手册

日期：2026-09-27。对应系统审计 P2-25。本文件是恢复操作的唯一正式说明；数据库迁移仍使用各自明确的维护入口，不能把恢复演练当作升级迁移。

## 当前事实与恢复承诺

Empire 是 Windows 单机桌面应用，不是跨主机高可用系统。MySQL 是业务数据及任务、网站、下载设置的唯一持久来源；Redis 按用户确认使用纯内存模式；应用代码、忽略的本地连接配置和数据库数据位于不同位置。

截至本文件日期，项目中**未登记已验证的 MySQL 备份位置、备份周期或外部副本，也没有可引用的既有恢复耗时**。因此不能承诺数据库磁盘损坏后的固定 RPO/RTO。下面的目标是操作分级和验证标准，不虚构尚未完成的保障。

| 故障 | 可保留 | 必然或可能丢失 | 当前 RPO | 当前 RTO |
| --- | --- | --- | --- | --- |
| 仅正常关闭并重开 Empire | MySQL、仍在运行的 Redis 全部状态 | 未保存的界面草稿 | 已提交数据为 0 | 通常为应用重启时间，未作为服务级指标承诺 |
| Empire 异常退出，Redis/MySQL仍运行 | MySQL；Redis 已成功入队数据、断点和计划状态 | 尚未入队的当前响应、界面草稿 | 从最后一次成功提交点恢复 | 未实测；重开后按正式队列恢复 |
| Redis 服务或电脑重启 | MySQL 业务数据和 app_setting | 待归档消息、断点、next_due、许可/冷却、摘要、采集/归档/错误记录 | 所有仅在 Redis 的未归档及运行状态全部丢失 | 服务恢复后重新采集；没有持久 Redis 恢复时间承诺 |
| MySQL 正常重启且数据目录完好 | 已提交事务由 InnoDB redo/undo 恢复 | 未提交事务 | 预期为最后已提交事务 | 未实测，取决于 InnoDB 恢复和数据量 |
| MySQL 逻辑损坏、数据目录或磁盘丢失 | 仅能恢复到最近一次已验证备份 | 该备份之后的 MySQL 修改；没有备份时可能全部丢失 | **当前无已登记备份，无法保证** | **当前未完成真实备份恢复演练，无法保证** |
| `%LOCALAPPDATA%\Empire\config.toml` 丢失 | MySQL 中 app_setting 与业务数据 | 数据库/Redis 密码及本机路径配置 | 当前未登记安全副本 | 由随包空白模板重新安全配置后重启；未实测 |
| 应用目录损坏 | MySQL及独立服务数据目录 | 未提交源码修改、未另存的本地配置 | 取决于 Git/制品和配置副本 | 重新部署同一构建并恢复配置；未实测 |

Redis 丢失后不得从 `collection_state` 推断未归档消息已经存在，也不得伪造运行记录、断点或最近 Redis 核验时间。重新打开 Empire 后，从头或按 MySQL 完整性重新采集；股票重新形成完整列表，新闻从第一页及已归档上界继续，日历根据 SQL 完整月份补齐。MySQL 中已归档数据仍可浏览。

## 日常故障处理顺序

1. 停止新的操作，记录故障时间、Empire 构建身份、受影响服务和最后可见状态。不要清 Redis、删锁文件、删除 redo/undo 或反复执行迁移脚本。
2. 若 Empire 仍有响应，正常关闭并等待采集、归档和数据库操作退出。服务故障时不要用强制结束数据库进程代替正常停止。
3. 先执行只读 `python -X utf8 -m empire doctor`。MySQL 可用而 Redis 不可用时，可继续浏览已归档数据，但不要宣称采集链路正常。
4. 按上表识别故障域。Redis 内存状态丢失走“重新采集”；MySQL 数据目录完整走服务自身事务恢复；MySQL 数据丢失才走已验证逻辑备份恢复。
5. 恢复后先核对业务表、统一状态和配置，再启动采集。未知 schema、表缺失或摘要不一致不能用清队、自动建表或跳过校验解决。

## 创建可验证的 MySQL 逻辑备份

本节不会由应用或发布门禁自动执行。启用周期备份、额外写盘、远端副本、保留周期和凭据权限会扩展当前运维范围，须由用户另行确认。

1. 正常关闭 Empire，确认没有其他 Empire 写入者。Redis 待归档 Stream 应为 0；非零时先用当前版本完成归档，不能为了备份清队。
2. 在数据库外的受保护目录创建备份。不要把密码放进命令行、脚本或报告；`--password` 让客户端交互读取。

```powershell
mysqldump.exe --host=127.0.0.1 --port=3307 --user=<用户名> --password `
  --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 `
  --result-file=D:\EmpireBackups\empire-YYYYMMDD-HHMMSS.sql empire
```

3. 在应用仍关闭、业务库没有写入的条件下生成源清单，并将备份文件大小和 SHA-256 记入同一清单。工具使用只读一致性快照，不执行 DDL/DML，也不输出密码或完整配置。

```powershell
.\.venv\Scripts\python.exe scripts\mysql_recovery_inventory.py `
  --config "$env:LOCALAPPDATA\Empire\config.toml" `
  --backup-file D:\EmpireBackups\empire-YYYYMMDD-HHMMSS.sql `
  --output D:\EmpireBackups\empire-YYYYMMDD-HHMMSS.inventory.json
```

4. 将 SQL 和 inventory 一起保存，限制文件 ACL，并把复制、加密、离机位置及保留周期记录在本机运维记录中。只有通过下一节恢复比对的备份才可标记为“已验证”。

## 在隔离数据库执行恢复演练

恢复演练禁止覆盖 `empire`。目标必须是一个此前不存在、名称以 `_restore_drill` 结尾的新数据库；工具也会拒绝把源库或普通数据库当恢复目标。

1. 使用有权限的维护账号明确创建新库。若同名库已存在，先停止并人工核查其所有者，不要由脚本自动 DROP。

```sql
CREATE DATABASE empire_restore_drill CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

2. 导入备份。使用 MySQL 客户端的 `SOURCE`，避免 PowerShell 文本重定向改变 SQL 文件字节。

```powershell
mysql.exe --host=127.0.0.1 --port=3307 --user=<维护用户名> --password `
  --database=empire_restore_drill `
  --execute="SOURCE D:/EmpireBackups/empire-YYYYMMDD-HHMMSS.sql"
```

3. 从随包空白模板单独创建恢复配置，只把 `[mysql].database` 指向 `empire_restore_drill`。Redis 配置不会被此只读验证工具使用，但仍不得指向或清理共享 Redis。
4. 比对全部五张正式表的列、主键、索引、引擎、逐行数量和稳定内容摘要：

```powershell
.\.venv\Scripts\python.exe scripts\mysql_recovery_inventory.py `
  --config D:\EmpireBackups\restore-drill.toml `
  --compare D:\EmpireBackups\empire-YYYYMMDD-HHMMSS.inventory.json `
  --output D:\EmpireBackups\empire-YYYYMMDD-HHMMSS.restore-result.json
```

结果必须为 `passed=true` 且 differences 为空。`stock`、`finance_news`、`trade_calendar`、`collection_state` 和 `app_setting` 缺一不可；只比较行数不算通过。记录开始/完成时间，才可得到本机实际 RTO；备份时间与故障点的间隔才是可声明的 RPO。

5. 演练完成后保留 SQL、源清单和结果报告作为证据。隔离数据库的删除属于独立破坏性维护，不由验证工具执行；明确核实名称和证据后再由数据库管理员处理。

## 恢复到生产的决策门

只有在原业务库不可继续使用、已选择一份 `passed=true` 的备份并明确接受其 RPO 后，才可以计划生产恢复。生产恢复会改变或替换业务数据，不属于本手册自动授权范围，必须单独确认准确目标、停机窗口、回退副本和执行人。应用启动、`init-db`、迁移脚本和恢复清单工具都不得自动完成这一步。

恢复完成后至少核对：五表清单一致；三类业务页面可读；`collection_state` 每项目一行；任务、网站和下载配置存在；Redis 作为空的临时状态重新开始；首次采集不得用旧摘要授权清队。随后执行 `empire doctor` 和当前版本发布门禁，再正常打开应用。

## 尚未完成的外部保障

- 尚未登记备份介质、周期、加密、ACL、离机副本、保留周期和告警责任人。
- 尚未用真实备份完成隔离 MySQL 恢复，所以真实 RPO/RTO 仍为空，不得写成已达标。
- 当前不恢复 Redis AOF/RDB，也不启用 MySQL binlog；这是已确认的低写盘策略。若以后要求时间点恢复或跨机容灾，需要重新审阅写盘、容量、安全和权限影响。
