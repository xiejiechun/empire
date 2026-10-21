<!-- topic:数据库参考|Redis fingerprints -->
<!-- summary:业务内容摘要：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis fingerprints

## 用途与归属

业务内容摘要。统一归档器通过 FingerprintCache 独占管理；数据集声明业务身份/内容/版本，插件不能另建完整业务缓存。

## 结构与身份

键模板：`<namespace>:archive:fingerprints:v1:<dataset>:<source>`

类型：**Hash**。

field 为声明的业务键，value 为 JSON {hash, version}。dataset 是摘要命名空间（如 stocks），不是每个 Envelope 的原始 dataset 名；股票 source=current 共用目录证明。

## 读写与关联

SQL 成功提交或确认同内容后才写；必须同时匹配 hash、合法版本和未过期 expiry 索引。命中免 MySQL（含 collection_state），不可信/缺失/损坏/过期回 SQL。SQL 拒绝旧版本不得缓存为当前。

## 保留与恢复

默认每数据集/来源最多 10000 键、最后成功确认后 7 天；容量与 TTL 由 archive 参数控制，Lua 原子维护 Hash/ZSET 并淘汰到期或最旧项。只存摘要/版本。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`pipeline/fingerprints.py`、`pipeline/archive.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[存储与归档规则](help:存储与归档规则)、[数据库职责与查阅](help:数据库职责与查阅)

资本范围准备先逐证券核对SQL完整单元的键和内容，再读取相同单元摘要补充时效；停复牌只对SQL已连续覆盖的同月范围读取精确checked_dates摘要。只读peek不刷新TTL、不清消息，缺失/损坏/过期/超前回SQL；不扩展范围或以时间掩盖集合缺口。
