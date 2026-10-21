# 同花顺当前指数及成分

本包拥有当前指数目录、完整成员、归档证明、正式查询和按需页面。bundle.py在builtin显式装配原插件/任务/数据集槽位，身份、schema和保存配置不变。contract.py拥有业务身份、边界和digest；跨业务index_code语法唯一位于contracts/security.py。source.py使用唯一sources/ths_catalog_html.py公共HTML树，collector.py复用共享下载/代理/频控、预取与统一入队归档，dataset.py持有SQL比较和证明，query.py提供正式查询与准备，ui.py按需创建页面。

初始化及后续刷新完整目录；每指数一个必要成员响应，按序校验和独立入队，整轮末确认归档。未完成轮次继续旧断点，Redis丢失后完整重查；来源暂无不推断真实零成员。只保存当前关系，不提供权重或历史调样。

专项为tests/test_ths_indices.py、tests/integration/test_index_archive.py。安全实采scripts/verify_indices.py复用共享私有生命周期，在不同server_uuid的13348 UUID库和owner前缀核对完整来源、入队、SQL证明及公开查询；scripts/measure_indices.py保持原容量规模与阈值。工具存在不代表已通过，动态证据见[E2记录](../../../../docs/evidence/architecture-e2-2026-10-20.md)，操作和字段见[指数说明](../../../../docs/ths-indices.md)。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
