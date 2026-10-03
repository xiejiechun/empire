# 增发送配三张独立业务表

显式入口：`scripts/migrate_capital_actions.py`。用户已要求开发三个采集组件，新增存储属于授权范围；无需丢弃旧业务数据。

执行前正常关闭 Empire，获取现有单实例锁并确认待归档 Stream 为零。只对 dividend_plan、additional_issue、rights_issue 执行 CREATE TABLE IF NOT EXISTS，结构不兼容时失败，不重建旧表。全部现有 Empire 表执行有序行数及内容 SHA-256 核验，DDL 后再次核验一致。维护可重跑；已存在的三张表也纳入保护。MySQL DDL 不假称事务回滚，部分创建后可安全重跑。

字段定义见 [schema.sql](../schema.sql)，生命周期和业务身份见 [增发送配说明](../../docs/tdx-capital-actions.md)。本轮已完成创建；原有六张表的数量、内容摘要前后一致，详细本机证据为 build/capital-migration.json。无旧格式业务数据，因此没有运行时迁移或业务搬运。
