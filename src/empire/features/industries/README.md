# 同花顺当前行业

本包contract/source/collector/dataset/query/ui拥有当前行业完整集合；bundle在原槽位贡献原插件/任务/页面，不新增运行时插件种类。HTML Node/Document/one由sources/ths_catalog_html.py唯一提供，指数与行业各自持有业务解析。

先读取完整目录，用共享有界预取下载各行业完整成员。所有单元通过后只入队一份industry.snapshot，统一归档在同一事务比较industry、industry_member及项目状态；未收齐不发布部分集合。下载中断重新下载尚未发布的集合；已入队整份先等待统一归档重放。Redis丢失后重查当前集合，不承诺历史归属。

正式查询和准备检查位于query.py，页面位于ui.py；公共preparation和预览组件保持既定路径。tests/test_ths_industries.py、tests/integration/test_industry_archive.py验证集合、空/分页/修订/重放；安全工具scripts/verify_indices.py --kinds industries核对完整来源→私有Redis→统一归档→SQL及公开分页集合。当前行业设计卡仍为明确legacy_baseline，不冒称行业容量新测。见[行业说明](../../../../docs/ths-industries.md)和[E2进展](../../../../docs/evidence/architecture-e2-2026-10-20.md)。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
