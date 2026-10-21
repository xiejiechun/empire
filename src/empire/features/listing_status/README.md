# 暂停恢复终止上市

contract公开日期、事件身份、月份证明valid_proof及FINGERPRINT_VERSION；source负责一次完整日响应的全市场总数核对与沪深A股过滤；collector使用共享下载/代理/预取，月内逐日校验后原子入队，整轮末等待统一归档。dataset负责完整月份替换和旧版本保护，query提供SQL列表/详情/补缺，audit核对月份集合及数据准备用途，ui按需创建，bundle保持原槽位。

入口、生命周期、状态丢失恢复和来源限制见[业务说明](../../../../docs/tdx-listing-status.md)。不按当前股票名单过滤、不推断永久退市；空月须有合法完整日响应及内容证明。公共preparation、摘要、入队、归档和调度保持唯一正式路径；未改表或用户保存设置。

业务专项为tests/test_listing_status.py、tests/test_listing_scope_prefetch.py与tests/integration/test_listing_status_archive.py；安全实采和容量工具须通过当前隔离验证后执行。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
