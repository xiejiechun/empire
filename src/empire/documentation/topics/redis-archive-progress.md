<!-- topic:数据库参考|Redis archive-progress -->
<!-- summary:增量归档进度：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis archive-progress

## 用途与归属

增量归档进度。统一归档器写；CollectionState/ArchiveConfirmation 供任务完成确认读取。

`diagnostics/redis_evidence.py` 只读指定 job_key 的现有进度，正文上限 128 KiB；超限或缺失保持部分/未知，不刷新进度或摘要。

## 结构与身份

键模板：`<namespace>:archive:progress:<job_key>`

类型：**String / JSON**。

batch_id、page、status、row_count、error_text、observed_at；同批次不后退，invalid 状态保持，旧观察批次不覆盖新状态。

## 读写与关联

page 是来源入队顺序，不必是 HTTP 页码。整轮入队结束后，还必须检查本批次 Stream 无残留；单独最高成功页不能证明完成。缺失时只读 SQL progress 作后备。

## 保留与恢复

无 TTL，每 job_key 最近一条；SQL 仅保存最近回源确认进度，不是本键完整备份；Redis 丢失后不恢复缓存确认上界。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`pipeline/archive.py`、`infra/collection_state.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[MySQL collection_state](help:MySQL%20collection_state)、[数据库职责与查阅](help:数据库职责与查阅)
