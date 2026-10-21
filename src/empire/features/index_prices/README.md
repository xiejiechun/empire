# 同花顺指数历史日行情

本包拥有年度行情contract/source/collector/dataset/query、UI及chart；bundle保留原插件、任务、数据集、页面和顺序。目录只通过公开查询获取，摘要使用indices.contract.digest，指数代码语法使用公共security，不导入别人的采集执行器。

每指数先获取last快照及年份计划，以共享有界预取下载需要的完整年度，按序入队后继续，整轮末确认归档。普通续采补缺与近期修订；fresh回查全部来源年份，不删除已有历史。失败不越过失败年度，SQL提交后确认失败走统一重放；Redis丢失后依据SQL年度证明补缺。没有第二队列、归档器或all.js双读。

缺OHLC、缺成交额、负量额和来源占位保持既定区分；年度完整不等于所有策略可用。固定399317/2014-12-05负成交额原样保留，正式查询标为量额异常；页面不补造来源值。query提供有界列表、有限完整图表和年度audit，chart负责绘图。

专项为tests/test_ths_index_prices.py、tests/integration/test_index_price_archive.py。scripts/verify_index_prices.py先正式采集指数目录，再验固定指数所有来源年份、入队/SQL/公开列表与图表集合；私有资源/取消/清理复用共享生命周期。scripts/measure_index_prices.py保留100000行及原阈值。工具不代表已验收，见[E2记录](../../../../docs/evidence/architecture-e2-2026-10-20.md)和[行情说明](../../../../docs/ths-index-prices.md)。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
