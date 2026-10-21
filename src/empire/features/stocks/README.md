# 当前股票目录

`bundle.py` 统一贡献新浪与同花顺股票列表的原有采集、查询、页面及同一股票数据集。列表仍只有一份，保留原来的任务 ID、插件 ID、来源范围、整体集合校验和新版本优先规则。

| 修改内容 | 正式入口 |
| --- | --- |
| 标识和纯规范规则 | `contract.py` |
| 来源解析、共享下载和按序采集 | `ths_source.py`、`download.py`、`sina_collector.py`、`ths_collector.py` |
| 统一数据集、事务内替换与摘要声明 | `dataset.py`、`publication.py` |
| 股票归档确认与回调登记 | `confirmation.stock_status`、`bundle.py` |
| 调用方连接内的当前目录证明 | `api.current_directory(connection, namespace, *, lock=False)` |
| 纯字段/集合检查及正式 SQL 核查 | `audit_rules.audit_stocks`、`audit.check_stocks` |
| 正式列表查询与页面 | `query.py`、`ui.py`、`preview.py` |

公开 `current_directory` 使用传入的连接，按现有版本选择新浪/同花顺的最新目录证明。它不建立、关闭或提交事务，写入方显式使用 `lock=True`。数据集导入同一函数履行统一归档器 `aggregate_current` 的既有映射协议；调用方不得另建目录读实现。

`publication.read_snapshot_marker` 为原有纯 Redis 标记校验的唯一实现，由本包 `confirmation.stock_status` 使用。bundle 以 `stocks.snapshot` 登记无状态回调，股票数据贡献显式声明需要该回调；组合入口核对归属、缺失、重复及多余处理器后，在原 7200 槽位注入统一确认提供者。共享提供者的插件身份与服务契约保留，不隐式导入股票实现。原确认函数仅把 mysql/redis 访问改为明确参数，标记格式、时区、版本和来源规则保持原样。标记不能替代完整业务摘要授权清理；归档成功清队仍由公共管线处理。

验证入口包括 `tests/test_sina_universe.py`、`tests/test_ths_universe.py`、股票归档集成回归、`tests/test_preparation.py`、`tests/test_foundation_public_api.py` 及统一装配身份检查。新 API 回归针对动态映射丢失和调用方连接边界；`test_shared_boundary_injection.py` 另验证回调缺失/重复/归属、参数传递、异常和取消。确认注入还须重跑冷热确认、旧响应、提交后重放、Redis丢失恢复及装配身份回归，不能仅按导入迁移免验。迁移文本相等不代表测试或真实采集已通过。

日常操作继续使用“采集管理”和“数据浏览 → 数据目录”。此目录迁移不改变任务保存、生效或生命周期规则；新增来源解析或生命周期变更仍须执行采集开发指南的实采准入。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
