<!-- topic:数据库参考|Redis stocks-committed -->
<!-- summary:股票最近成功核验：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis stocks-committed

## 用途与归属

股票最近成功核验。统一归档器在整份列表成功后写，ArchiveConfirmation 读取；归属按来源。

## 结构与身份

键模板：`<namespace>:stocks:committed:<source>`

类型：**String / JSON**。

与 result 同结构，保存最后 complete 批次和完成时刻；包含相同内容/缓存核验成功，不等于最后业务修改。

## 读写与关联

股票界面“更新于”取 SQL publication 的最后实际变化；本键代表最近成功核验。它不是业务摘要，不能据其直接删除待归档数据。

## 保留与恢复

无 TTL，每来源最近一条；应用重启且 Redis 未重启可读。Redis 丢失后 SQL 不保证恢复其后的无变化核验上界。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`datasets/stocks.py`、`pipeline/archive.py`、`infra/archive_confirmation.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[MySQL stock](help:MySQL%20stock)、[数据库职责与查阅](help:数据库职责与查阅)
