# 最新打磨：空间分配与滚动

已修复详情返回后目录高度塌缩，统一目录、财报、行情的剩余空间布局。验证与反例见 [布局打磨记录](LAYOUT-REVIEW.md)。

# 当前版本：50项全目录数据预览

目录中每一项均直接打开数据预览；取消“仅看可交互预览”筛选与只读说明占位分支。查看 [50项覆盖与验证](DATA-PREVIEW-COVERAGE.md)。以下为历史迭代记录。

# 当前版本：专属数据视图

按数据语义重构股票档案、行情图表、新闻阅读器、日历与三大报表。核对范围及预览限制见 [数据设计记录](DATA-REVIEW.md)，当前交互验证脚本为 `qa/review-bespoke.cjs`。以下为历史版本记录。

# 数据浏览评审更新

当前启动进入数据目录。可勾选“仅看可交互预览”，体验股票、行情、快讯、日历与利润表。详见 [数据浏览评审](DATA-REVIEW.md)。

> 后续实施入口：[新版桌面采集管理接入实施文档](../../docs/desktop-collection-integration-plan.md)（2026-10-29，待实施）。

# 当前评审版本：V5 功能补齐

保留已认可的 V5 布局。本轮对照现有 Python 客户端补齐管理操作和来源说明；详见 [功能核对与待补项](FEATURE-PARITY.md)。以下历史版本记录不代表当前版本。

# Empire 桌面设计预览 V3

当前评审重点为完整采集管理工作流，详见 [管理设计与范围](MANAGEMENT-REVIEW.md)。使用 Electron + React + Ant Design，所有数据和操作均为设计示例，不连接正式服务。

已安装依赖时运行 `npm.cmd run build`、`npm.cmd run desktop`。首次安装另执行 `npm.cmd ci --no-audit --no-fund` 与 `npm.cmd run setup:desktop`。当前窗口为“Empire · 设计评审 V3”，使用独立 `.preview-profile-v3`。

从顶部采集管理进入任务、已归档任务、运行记录、平台与出口、共享资源。任务底部“资源与身份”可进入共享配置；平台页切换“采集出口 / 平台身份”。数据浏览保留上一轮目录与财报设计，没有常用/最近打开，没有双排顶部导航。

当前截图为 qa-output/v3-*.png，验证脚本为 qa/review-management.cjs，结果为 qa-output/v3-checks.json。旧版本截图仅供历史比较，旧脚本不代表当前导航验证。

正式迁移设计见 DESIGN.md，原页面登记见 route-inventory.json。当前仅供设计确认，未迁移生产业务。

当前体验优化版为 V3.1，入口与记录见 MANAGEMENT-REVIEW.md 的 V3.1 部分，截图 v31-*.png，验证 qa/review-ux.cjs。

当前版本 V4：运行记录并入任务；采集出口按 IP 分组；身份管理独立。以 qa/review-v4.cjs 与 v4-*.png 为当前证据。

最新 V4.1 将运行记录与本轮事件整合为统一轮次日志；证据以 qa/review-v41.cjs、v41-*.png 为准。

最新 V5：平台→采集项两级目录，单任务工作区与轮次卡片。使用 qa/review-v5.cjs、v5-*.png 查看本轮证据。

最新 V5.1：单工作区、行内事件详情与采集项目进度。当前证据 qa/review-v51.cjs、v51-*.png。
