# 数据准备与用途验收

本包拥有数据准备需求目录、研究用途选择与检查聚合、缓存、结果及页面。跨业务的 `CheckEvidence`、`PreparationContribution`、`ComputationContribution` 等协议保留在唯一原路径 `empire.contracts.preparation`；`PreparationScope` 及其输入选项保留在 `empire.contracts.preparation_scope`。业务提供者直接使用这些公共契约，不设转发模块或第二个插件注册器。

| 修改内容 | 正式入口 |
| --- | --- |
| 证据/贡献结构 | `empire.contracts.preparation` |
| 需求目录和研究选择/检查 | `catalog.py`、`foundation.py`、`events.py`、`markets.py`、`processing.py`、`research.py` |
| 跨业务范围与输入选项 | `empire.contracts.preparation_scope` |
| 纯通用证据和三日观测时效 | `evidence.py` |
| 正式检查聚合、缓存和计算调度 | `query.py`、`cache.py`、`computation.py`、`inventory.py`、`results.py` |
| 页面布局、交互、详情和范围草稿 | `ui.py` 与 `ui_*` |
| 已有最终装配阶段 | `composition.plugins_for(plugins)` |

装配顺序保留：其他业务插件先构造，再把它们的贡献与完整实例列表传给 PreparationPlugin，最后创建原 PreparationUiPlugin。`composition` 只是原有表达式的归属入口，不重新扫描模块、不启动服务，也不改变插件身份。

股票、日历和停复牌 SQL 审计分别属于各自业务；本包只保留通用证据规则，旧 `preparation_checks` 混合模块退役。发布证据读取仍由 `core/preparation_release.py` 负责，因为它管理程序资源/发布根目录，不随业务目录移动。

“数据准备”页面继续分别显示开发验证和实际归档结果。测试证据、来源范围和已采完进度不可互相替代；未知或不可用信息不冒充通过。查询取消与编辑草稿仍由自身页面及公共 QueryScope 管理。

验证入口为数据准备、用途范围、页面草稿、插件装配/启停相关测试，以及统一文档和发布门禁。目录整理的 AST 证据只支持代码归属审查，不能替代这些运行验证。
