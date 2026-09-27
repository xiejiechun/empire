# 当前发布信息与正式路径维护（历史记录）

本阶段已执行完成，执行脚本已退役。下文保留当时变更事实，不作为当前操作指引；后续统一状态维护见 [collection_state](2026-09-26-collection-state.md)。

适用于已经完成配置持久化及北京时间迁移的版本；旧维护脚本已退役，历史变更记录仅供审计。新安装使用 schema.sql，不运行历史转换。应用启动不执行 DDL。

- 股票：先验证每来源批次及时间一致，将发布身份和数量复制到 stock_publication，核对后移除 stock 的 generation/started_at/updated_at 及旧索引。
- 新闻：last_seen_at 原值重命名为 version_observed_at，不改时间和新闻内容。该字段表示当前入库版本的观测时间，相同内容不刷新。
- 日历：表结构不变，updated_at 仍只表示该日期实际变更时间。
- 配置：旧分钟值通过维护入口乘以 60，正式字段为 interval_seconds；原有秒值优先，保留 next_due。
- 队列：确认归零后退役旧 archive 消费组，只清除领取元数据，不删除业务消息。运行时仅扫描与 XDEL。
- 代理：只读核实在线 JSON 目录契约（proxy 无协议时明确使用 SOCKS5H），不输出连接串，不修改 RouterProxy key。

MySQL DDL 会隐式提交，不声称整个迁移可事务回滚。脚本按现有列识别进度，可重复执行；失败时保持应用关闭、修正原因后继续，禁止运行旧程序写入。移除的股票元数据已完整保存在发布表，新闻字段原值保留。

迁移前后按主键计算三张业务表的数量和内容 SHA-256，并核对发布条数。结果保存在 artifacts/formal-paths-migration.json。股票及日历最新无变化核验上界仍只在 Redis，服务重启后不保证恢复该上界。
