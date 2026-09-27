# 采集器契约验收

## 范围与取舍

本轮关闭审计 P2-17 中三类采集器重复生命周期和关键能力隐式字典契约。没有建立继承式 `BaseCollector`，也没有把以下业务规则移入公共层：

- 股票：总数、倒序边界、完整分页、尾页和整批发布。
- 新闻：来源 ID 倒序、上次高水位覆盖及可见窗口缺口。
- 日历：历史缺月计划、整月完整性和未来月份修订。

公共层只保留跨来源完全相同的控制语义，避免一个基类通过条件分支重新耦合所有插件。

## 唯一正式路径

`src/empire/contracts/collector.py` 声明：

- `IngestPublisher`、`ArchiveConfirmation`、`CollectionRecords`、`QueueReservation` Protocol。
- `Checkpoint`、`ArchiveStatus` 以及股票、新闻、日历运行结果 TypedDict。

`src/empire/plugins/collectors/support.py` 提供四个无状态组合函数：

1. `wait_for_capacity`：仅等待可恢复背压，同时更新 collecting/paused 状态。
2. `publish_with_capacity`：始终通过 `ingest.publish_page` 发布；容量竞态回到同一等待入口。
3. `wait_for_archive`：统一处理 pending、complete 和 invalid，不复制轮询判断。
4. `record_error_safely`：只在 HTTP 层尚未记录时写入一次；诊断 Redis 失败不覆盖原始异常和断点。

股票、新闻、日历均已迁移到这四个入口，旧的本地 while/try/except 模板已删除。测试替身也迁移现行方法签名，没有增加旧签名适配器。

审计中“按职责拆分 archive”所指的扫描调度与完成确认在此前工作包已经分别落于 `pipeline/archive_queue.py` 和 `infra/archive_confirmation.py`；数据集分发也已由 `DatasetContribution` 接管。当前 `archive.py` 保留统一工作循环、事务调用和确认后清队职责。本轮不再为相同职责增加一层包装或第二套协调器。

## 异常语义

- `BackpressureError` 表示容量可能恢复，辅助函数等待后重试。
- `BatchReservationError` 表示预留已释放、属于其他任务或额度不足以覆盖当前发布；继续等待不会恢复，因此直接结束本轮，由正式 checkpoint 决定下一轮恢复位置。
- 取消仍传播 `CancelledError`，不写成业务错误；股票持有的整批预留在 finally 中释放。
- 归档返回 invalid 时抛出来源可见的错误，不把 checkpoint 标为 complete。
- 错误记录写入失败只增加 `diagnostic_error`，原始采集异常保持为调用结果。

## 静态与运行验证

开发依赖加入 mypy，`python -m mypy` 对采集公共契约和辅助实现执行 strict 检查。`empire/py.typed` 标记当前包为部分类型化：严格范围是本轮正式公共边界，不宣称整个历史代码库已经完成严格类型化。自动负例构造一个把 `expected_revision` 拼成 `expected_revison` 的调用，要求 mypy 返回 `Unexpected keyword argument`。

运行测试覆盖：背压暂停后恢复、发布和容量检查竞态、失效预留不循环、complete/invalid 归档结果、诊断写入失败、HTTP 已记录错误不重复保存、三类断点续采与业务差异。新增第四采集器只需依赖 Protocol 并组合辅助函数，不需要复制这些控制循环或修改中央归档器。

本轮在真实 Redis/MySQL 隔离测试范围执行全套自动测试：851 项通过；另有 2 项仅因当前 Windows 账户没有符号链接权限而跳过。Ruff、严格 mypy、依赖一致性及差异空白检查均作为交付门槛。测试不重启共享服务、不清空共享 Redis，也不删除业务数据。
