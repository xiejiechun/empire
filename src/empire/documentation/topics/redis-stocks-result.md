<!-- topic:数据库参考|Redis stocks-result -->
<!-- summary:股票最近归档结果：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis stocks-result

## 用途与归属

股票最近归档结果。股票数据集声明 key，统一归档器写最近结果，ArchiveConfirmation 读取。按 sina/ths 来源分别保存结果，SQL 股票目录仍只有一份。

## 结构与身份

键模板：`<namespace>:stocks:result:<source>`

类型：**String / JSON**。

snapshot_id、status、row_count、expected_count、error_text、finished_at、started_at；最近 complete/invalid 等归档结果，可能覆盖此前成功结果。

## 读写与关联

确认股票整轮状态时与 committed、SQL 状态和待归档消息共同判断。这个结果不是授权跳过 SQL 或清队的内容证明。

## 保留与恢复

无 TTL，每来源最近一条；错误结果不能覆盖股票正式业务内容。Redis 丢失后不能恢复所有最近核验时间。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`datasets/stocks.py`、`pipeline/archive.py`、`infra/archive_confirmation.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[股票列表](help:股票列表)、[数据库职责与查阅](help:数据库职责与查阅)
