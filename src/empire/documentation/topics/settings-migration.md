<!-- topic:技术参考|配置表与迁移 -->
<!-- summary:核对配置表与迁移的正式字段、规则和维护边界。 -->
# 配置表与迁移

## 字段与规则

MySQL `app_setting` 是配置表，独立于业务数据表，不通过业务归档队列保存。点击保存后立即提交事务；相同配置不重复写库，也不刷新更新时间。

[MySQL app_setting](help:MySQL%20app_setting) 负责配置结构和保存/生效契约。

MySQL 保存值优先；没有保存值的新任务采用插件声明的推荐计划，新网站组采用 TOML 初始值。域名范围由本机 TOML 声明；用户保存的网站频控与并发策略以 MySQL 为准。Redis 的 policy 只是运行副本，不能覆盖 MySQL；许可时间和 HTTP 429 冷却仍只在 Redis 中。

下载资源在“采集管理 → 下载资源”保存，`kind=download`、`setting_key=global`；没有保存值时使用程序默认值。页面同时区分当前运行、已保存和重启待生效；正常退出并重开软件后统一使用新值，不自动打断当前采集。“恢复默认”只修改草稿，仍需保存。资源数值只有 MySQL 这一条持久配置路径，TOML 仅保留机器路径 `http.download_directory`。

规划出口设备支持 100、200 至 1000 台共十档，一键推荐只更新规划设备、全局窗口和共享缓冲草稿，不改变单响应/文件设置、网站频率或任务代理开关。默认 100 档为 128 窗口/512 MiB；旧九字段 SQL 下载配置须通过 `scripts/migrate_download_capacity.py` 显式补齐，运行时不迁移。自动站点只有显式指定维护选项才改为跟随全局，固定策略和频率不变。

旧 TOML 的 http.buffer_budget_bytes、http.download_quota_bytes、http.disk_free_margin_bytes、http.file_concurrency 由 `scripts/migrate_download_settings.py` 显式迁移；运行时发现这些旧数值字段会拒绝启动并提示维护。先正常关闭 Empire，核对已有 SQL 配置及待迁移值；SQL 冲突不覆盖，迁移成功后退役 TOML 旧键，目录路径不变。不需要业务表结构迁移，不删除已有文件或业务数据。

当前版本升级：正常退出 Empire，确认待归档队列为零后显式运行 `python scripts/migrate_collection_state.py`。脚本迁移至统一状态表，核对业务数量和内容摘要后退役股票专用发布表。旧分钟配置及北京时间维护已完成，旧脚本退役，历史证据保留在 sql/changes。应用启动不会自动迁移。

全新环境用 `python -m empire init-db` 创建缺失表。正常启动只检查表结构，不自动改库。数据库连接信息在 EXE 同目录 `config.toml`（源码为项目根目录），勿在文档或日志复制密码。
