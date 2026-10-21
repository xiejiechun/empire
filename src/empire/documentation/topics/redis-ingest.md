<!-- topic:数据库参考|Redis ingest -->
<!-- summary:待归档业务队列：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis ingest

## 用途与归属

待归档业务队列。统一入队器校验后发布，统一归档器扫描、处理并 XDEL；RedisStore 只提供连接和正式 stream 名。

`diagnostics/redis_evidence.py` 只读队列长度及至多 5 条消息的抽样，累计正文达到 256 KiB 后停止取下一条。报告区分全局数量、项目下界与未知；未遍历全队列时不能声称该项目没有待归档数据，不确认或删除消息。

## 结构与身份

键模板：`<namespace>:ingest`

类型：**Stream**。

消息 field 为 envelope：event_id、schema_version、dataset、source、job_key、batch_id、observed_at、raw_payload；raw_payload 是规范业务契约内容，不是长期原始响应库。Stream ID 由 Redis 分配。

## 读写与关联

发布消息与 checkpoint revision/cursor 在同一 Lua 中提交；入队成功立即唤醒，60 秒扫描兜底。业务完整批次才归档，未知契约按归属隔离或全局阻断，原消息保留。

## 保留与恢复

不设置 TTL，不按日志配额截断有效业务。成功插入、更新、相同内容、可信摘要命中或旧版本确认均删除对应消息；失败保留。未收齐分页暂存；有明确新断点证明被替代的旧不完整批次才释放。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/redis_store.py`、`pipeline/ingest.py`、`pipeline/archive.py`、`pipeline/archive_queue.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[存储与归档规则](help:存储与归档规则)、[数据库职责与查阅](help:数据库职责与查阅)
