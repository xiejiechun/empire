# P3-29 文档契约与稳定证据验收

日期：2026-09-27。

## 单一事实来源

日常操作只引用当前正式路径：用户配置在 `%LOCALAPPDATA%\Empire\config.toml`，任务、网站频控和下载资源配置在 MySQL `app_setting`，Redis 只保存会随服务重启丢失的运行状态。数据库表名以 `sql/schema.sql` 为准，配置字段及默认容量以 `config/app.example.toml` 为准，依赖以 `requirements.lock` 为准。

历史审计和变更记录继续保留，不抹掉当时的问题、数据量与临时截图说明；历史值必须带日期或明确“当时/旧版”，不能再作为当前操作说明。被 `.gitignore` 排除的 `build`、`artifacts`、日志、截图和业务数据不提供伪稳定链接。

## 自动契约

`scripts/verify_documentation.py` 已进入发布门禁并检查：

- README、AGENTS、docs、deploy、SQL 变更记录及内置 Markdown 的相对链接存在，拒绝机器绝对路径和越出仓库的链接；`#L` 行号不能超出文件。
- Schema 必须仍为 `stock`、`finance_news`、`trade_calendar`、`collection_state`、`app_setting` 五张正式表，Windows 服务说明必须逐一覆盖。
- Windows 服务说明中的队列上限、高低水位和单页大小必须与示例配置一致，且不得再声称网站配置随 Redis 重启丢失。
- `config/local.toml` 只能出现在明确标记旧版或历史的上下文，不能被写成当前配置位置。
- 稳定发布摘要必须符合固定结构、具备源码身份、测试数量、三个 SHA-256 和完整便携验证，不得包含密码、连接 URL 或机器用户路径。

这不是自然语言全语义证明；复杂业务规则仍需评审。但高影响且反复漂移的表名、路径、容量、持久化和证据链接已成为可失败的发布条件。

## 稳定证据与详细制品

[脱敏发布基线](evidence/release-baseline-2026-09-27.json) 纳入版本管理，只保存版本、Git 基线、门禁结果、依赖/EXE 摘要、测试数量、便携验证布尔值和明确局限。它不保存本机绝对路径、密码、服务连接串、业务内容或截图。

`build/release-report.json`、容量明细、依赖在线查询、截图和日志仍是本轮本机详细证据，可重新生成但不提交。仓库基线负责“结论可定位”，详细制品负责“本机可深挖”；两者职责不同，不复制一份长期业务数据。

当前基线的 `working_tree_dirty=true` 是如实记录，不冒充干净提交。代码进入 Git 后，提交本身会固定完整树；以后发布应新增或更新有日期的基线，并保留必要历史，不覆盖成无法追溯的一句“全部通过”。
