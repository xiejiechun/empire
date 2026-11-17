<!-- topic:数据库参考|Redis fingerprint-expiry -->
<!-- summary:摘要到期索引：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis fingerprint-expiry

## 用途与归属

摘要到期索引。FingerprintCache 拥有写入/清理，与摘要 Hash 共用同一 Lua 事务。

## 结构与身份

键模板：`<namespace>:archive:fingerprints:v1:<dataset>:<source>:expiry`

类型：**ZSET**。

member 为 Hash 的相同业务键；score 为失效 Unix 秒数，由 Redis TIME 和配置 TTL 计算。只有 Hash 存在不证明可信。

## 读写与关联

get 会清理到期项；peek 只读原子核对，不续期不清理，用于数据准备/日历证据。异常超前到期索引不成为成功证据。

## 保留与恢复

通达信维护读取仍要求Hash和本到期索引一起有效，仅读不续期；按周期复用SQL证明也不续期。分红报告期核验时间存于collection_state，最终清单不创建此索引条目，证券业务指纹沿用原有TTL及清理规则。

与摘要同容量/TTL、默认 7 天/10000 键；失效必须同时处理 Hash 和 ZSET，禁止只删一边。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`pipeline/fingerprints.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis fingerprints](help:Redis%20fingerprints)、[数据库职责与查阅](help:数据库职责与查阅)

资本与停复牌准备读取现有有效期索引核验可信摘要；不会续期或重建证明，索引过期或Redis不可用使用SQL证据。

2026-10-29：远航财务摘要使用独立 `ths_yuanhang:financial` 来源桶，行情继续使用原桶。每桶独立容量，过期规则不变；显式迁移保留原索引到期时间，不刷新证明有效期。
