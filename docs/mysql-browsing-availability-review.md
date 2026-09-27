# MySQL 浏览可用性验收

## 范围

本轮关闭系统审计 P2-14：Redis 故障不再连带阻断已经提交到 MySQL 的股票、财经新闻和交易日历浏览。没有改变 Redis 纯内存策略、归档成功清队、可信摘要或采集完成语义，也没有增加第二套确认路径。

## 正式能力边界

- `stocks.query`、`news.query`、`calendar.query` 只依赖 `mysql.store`，分别读取 `stock`、`finance_news`、`trade_calendar` 及所需统一状态。
- 新的 `archive.confirmation` 是采集器确认归档完成的唯一入口，依赖 `redis.store` 与 `mysql.store`。股票 committed marker 异常时回源 `collection_state`；新闻和日历使用统一分页进度回源。
- 三个采集器已迁移到该能力。查询插件原 `batch_status` / `page_status` 已删除，没有保留兼容转发、双写或重复适配器。
- 股票查询的 namespace 由启动配置传入，不再为了读取 `collection_state` 依赖一个运行中的 Redis 对象。列表只返回 SQL publication；Redis 临时核验不可用时不生成 `verified_snapshot_id`。

## 故障行为

| 场景 | 结果 |
| --- | --- |
| MySQL 正常、Redis 启动失败 | 三类查询能力保持运行并可读取已归档数据 |
| Redis 不可用 | `archive.confirmation` 阻塞；采集、归档及临时核验不会伪装为可用 |
| Redis 恢复 | 恢复依赖插件即可，三类查询插件无需重启 |
| Redis marker 损坏、不可信或缺失 | 归档确认回源 MySQL；不能据损坏 marker 确认或清理消息 |

## 验证

- 故障单测使用启动即失败的隔离 Redis provider，验证三个查询插件保持 `RUNNING`、三类查询均返回 MySQL 结果，而 `archive.confirmation` 为 `BLOCKED`。
- 股票 marker 测试覆盖非法 JSON、超深 JSON、错误状态、身份、时间、时区、计数和完成顺序；全部回源 SQL 或安全拒绝。
- 三类真实 Redis/MySQL 归档集成测试覆盖缓存命中、缓存丢失、SQL 回源、提交确认、旧版本与失败留队，使用专属命名空间并只清理测试数据。
- 验收不把模拟 Redis 启动失败等同于真实服务断网压测；生产服务未被停止。
