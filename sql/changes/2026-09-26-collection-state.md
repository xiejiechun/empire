# 每项目一条统一已归档状态

适用于上一阶段已完成股票发布信息拆分、北京时间及配置迁移的安装。正常退出 Empire，确认待归档 Stream 为零，再显式运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/migrate_collection_state.py
```

应用启动不执行 DDL。全新环境使用 schema.sql，无需历史迁移。

- 创建 collection_state，以 namespace/project_id 为主键，每项目一行。
- 股票专用发布信息与 Redis 已确认进度迁入该行；新闻、日历使用同一表，日历保留每月 SQL/Redis 已确认观测的较新上界。
- 按主键核对三张业务表的数量与 SHA-256，核实股票发布条数，再退役 stock_publication。只清理已迁入的新状态对应的旧日历观测 Hash，不清空 Redis，不改 RouterProxy。
- DDL 隐式提交，不能承诺整次迁移原子回滚。失败保持应用关闭，处理原因后重复运行；已存在的新状态不覆盖。不得运行旧结构 EXE。

本机迁移成功，业务前后完全一致：stock 5568 行、finance_news 3128 行、trade_calendar 13527 行；统一状态 3 行、队列 0。首次报告位于 artifacts/collection-state-migration.json。

运行规则：Redis 可信摘要命中完全跳过 MySQL；缺失或无效回源，由业务写入与统一状态共享事务。状态不是全量摘要的第二份副本，也不是历史流水或未归档断点。SQL 仅保存最近回源确认的版本，Redis 丢失后不保证恢复之后缓存命中的每次核验时间。
