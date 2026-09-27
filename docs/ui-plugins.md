# 管理界面插件与代码组织

日常操作与原导航保持一致。系统设置的插件管理中，现在可以分别启停工作台、采集管理、股票、新闻、日历、系统管理、说明文档、采集出口和下载资源界面。停用界面只移除其页面，不会停用对应采集服务。启停偏好沿用本机配置保存机制，重启 Empire 后保留。

页面关闭或所属插件停用时，未保存的表单草稿随页面释放；普通导航、分页与后台刷新会保留已打开页面的草稿。全部界面停用后，启动占位页的“恢复界面插件”可恢复所有已登记 UI 插件。

## 代码边界

| 模块 | 职责 |
| --- | --- |
| `desktop/window.py` | 导航、按需创建/释放页面、退出流程 |
| `contracts/ui.py` | PageContribution 页面契约 |
| `plugins/ui/plugin.py` | UI 插件公共启停生命周期 |
| 各业务页面模块中的 UiPlugin 子类 | 自有页面声明及分类、来源登记 |
| `plugins/ui/common.py` | 公共表格、分页与格式化，不引用业务页面 |
| `plugins/ui/collection.py` | 采集管理插件声明，直接贡献独立页面 |
| `collection_views/base.py` | 通用异步查询、提交和反馈流程 |
| `collection_views/task_layout.py` | 任务列表及计划编辑器布局 |
| `collection_views/tasks.py` | 任务交互、进度展示和按任务保存的草稿 |
| `collection_views/sites.py` | 站点访问规则页面及其草稿 |
| `collection_views/history.py` | 采集历史筛选、详情和归档/错误记录组合 |

`TasksPage` 通过单层布局类组合界面结构与通用页面生命周期；任务、网站、历史分别拥有自己的查询条件和状态。通用基类不根据页面类型访问业务控件。

每个 UI 插件提供独立的 `ui.pages.<domain>` 能力，工作台为 `ui.pages.workspace`。Runtime 聚合当前运行的页面提供者，外壳无需知道具体插件。业务插件在 bootstrap 的内部白名单中显式登记，不扫描或执行外部任意插件。

新增页面先确定所属业务插件，再声明 PageContribution。需要独立启停的新领域新增 UI 插件。数据页继续通过 catalogued/category/source 进入可搜索目录，不为每个采集器创建固定菜单。

UI 文件以 300 行以内为目标，350 行为自动检查上限。测试同时覆盖插件停用/重启/恢复、导航懒加载、跨页草稿、保存过程中继续编辑、失败保留草稿与历史详情稳定性。
