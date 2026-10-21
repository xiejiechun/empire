<!-- topic:技术参考|Redis 键索引 -->
<!-- summary:逐项键索引迁至数据库参考。 -->
# Redis 键索引

## 查键与归属

完整逐项索引见 [数据库职责与查阅](help:数据库职责与查阅) 的 Redis 目录。每个键条目单独说明类型、值、写入/读取方、期限、清理和丢失恢复。

## 维护边界

不要清空共享 Redis。手工业务维护先停止归档并失效对应来源摘要及到期索引；错误修复登记项目/ID，先修复验证后按确切 ID 清理。网站正式配置在 [MySQL app_setting](help:MySQL%20app_setting)，旧 site-intervals 不是运行路径。
