# 2026-09-29 通达信历史停复牌表

本页为首次建表历史记录；现行主键已按 [来源记录身份迁移](2026-09-29-suspension-identity.md) 增加复牌时间维度。新安装使用 `sql/schema.sql`，不要用下方旧主键替代现行结构。

本变更只新增 `suspension_event`，不修改或删除现有业务数据。应用启动、升级和重启均不会自动执行。执行前正常关闭 Empire，确认待归档 Stream 为 0，并记录 `stock`、`finance_news`、`trade_calendar`、`collection_state` 的行数；执行后复核这些数量不变。

```sql
CREATE TABLE IF NOT EXISTS suspension_event (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    suspended_at DATETIME(6) NOT NULL,
    resumed_at DATETIME(6) NULL,
    suspension_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_note VARCHAR(100) NOT NULL,
    reason VARCHAR(500) NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, suspended_at),
    INDEX ix_suspension_start (source, suspended_at, market, code),
    INDEX ix_suspension_resume (source, resumed_at, market, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```

执行后核对：

```sql
SHOW CREATE TABLE suspension_event;
SELECT COUNT(*) FROM suspension_event;
```

新表初始应为 0 行。历史初始化由 `tdx-suspensions` 任务经过 Redis 入队和统一归档器写入；不要直接导入绕过校验。回退仅允许在确认表仍为空、Empire 已关闭且待归档 Stream 为 0 时执行 `DROP TABLE suspension_event`。已有业务数据后，删除表属于数据丢弃，必须另行授权。
