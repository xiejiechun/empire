<!-- topic:数据库参考|MySQL app_setting -->
<!-- summary:用户正式保存的任务、网站频控、下载资源配置。 -->
<!-- group:MySQL -->
# MySQL app_setting

## 用途与归属

采集任务的批量启动和批量停止复用单任务配置保存流程：逐项保存 enabled 启停状态，其他已保存配置保持；不提交界面草稿，不增加批量配置表或整批事务，部分失败通过逐项结果呈现。

用户正式保存的任务、网站频控、下载资源配置。

唯一配置写入器 `infra/settings.py`；任务由 `collection/control.py` 管理，网站和下载资源由 `infra/http.py` 加载。任务、网站、下载资源页面调用命令，不各自写 SQL。

按项目诊断通过 `diagnostics/project.py` 只读该任务已保存的一行配置，正文上限 16 KiB；与 Redis 运行副本分别显示，不启动任务或保存配置。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `namespace` | `VARCHAR(160) NOT NULL` | 配置/采集空间，取 redis.namespace；与业务来源不同。 |
| `kind` | `VARCHAR(16) NOT NULL` | task 任务、site 网站、download 下载资源。 |
| `setting_key` | `VARCHAR(120) NOT NULL` | task 为项目 ID，site 为网站组，download 为 global。 |
| `payload` | `JSON NOT NULL` | 按 kind 校验的配置 JSON：task 含计划/代理/重试/启停/archived；site 含出口间隔/全站保护/扩展模式/并发；download 为字节整数资源值。 |
| `updated_at` | `DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)` | 该行最近实际内容更新时刻，MySQL DATETIME 按北京时间保存。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (namespace, kind, setting_key)`

## 读写与关联

按 namespace/kind 读取、setting_key 定位；连接凭据只在程序目录 config.toml，不放在 payload。任务保存后计划生效、网络策略下一轮生效；网站规则作用于后续请求；下载资源保存后正常重启生效。

task 的 request_retries 统一允许整数0～100，首次请求另计；原默认2次及已保存值保持不变，保存后下一轮生效。

SettingsStore 直接事务保存，不进入业务队列；同内容不写。软件、Redis 或电脑重启后配置保留，运行计划重新构建。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

配置保存走 SettingsStore；旧下载配置转换用 scripts/migrate_download_settings.py / migrate_download_capacity.py，当前合法配置不需再次迁移。程序目录连接配置仅用 scripts/migrate_program_config.py 显式搬入，不存本表。

[执行采集与计划](help:执行采集与计划)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
