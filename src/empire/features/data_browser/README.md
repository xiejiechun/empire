# 数据目录与通用业务预览

本包拥有可搜索数据目录、证券候选查询、业务目录面板及工作台页面贡献的装配。`api.candidates(mysql, search, dataset, limit)` 是原有有界候选 SQL 的唯一实现；股票查询能力继续委托它，避免增加新的查询路径。

| 修改内容 | 正式入口 |
| --- | --- |
| 有界候选查询 | `api.py` |
| 搜索延时、候选状态和 QueryScope | `search.CandidateSearch` |
| 数据目录页与原页面贡献 | `catalog.DataCatalogPage`、`contribution.workspace_pages`、`bundle.py` |
| 业务目录状态和控件 | `directory.DirectoryPanel` |
| 公共预览布局、导航和卡片 | `empire.plugins.ui.preview_layout`、`preview_navigation`、`preview_cards` |

通用布局、导航、卡片、表格、分页和基础格式化均留在独立公共 UI 模块。共享 UI 不得依赖具体业务包，即使业务符号已公开也不能反向导入；业务页面只复用这些公共控件。

本包 `bundle.py` 在原 14800 槽位贡献既有 WorkspaceUiPlugin，并注入 `contribution.workspace_pages` 页面工厂。该工厂保留原工作台和目录 PageContribution 的身份、顺序及延迟页面导入；装配 bundle 时不构造 QWidget。共享 WorkspaceUiPlugin 仅调用明确注入的工厂，不再导入业务页面。页面身份、偏好恢复和切页行为须由装配及真实桌面验证确认。

候选查询保持原有输入长度、最多30条上限和正式 SQL 过滤，不在页面构造时触发采集。切页取消只读查询、保留未保存编辑和按身份保持选择等行为保持现有公共规则。

验证入口为预览候选、数据目录、导航、页面惰性创建、QueryScope 和 UI 大小门禁；修改公开控件时同时检查跨业务调用者。迁移后仍须执行文档覆盖、程序内说明与可见桌面验证。
