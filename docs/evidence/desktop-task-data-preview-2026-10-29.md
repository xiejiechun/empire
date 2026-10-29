# 任务内数据预览 · 2026-10-29

用户要求：不保留独立数据预览模块，从采集管理直接查看对应数据。

## 实现

- Electron 顶栏移除独立数据浏览入口；选择采集项后，在运行与记录旁进入数据预览。
- 55 个当前任务登记 79 个视图，复用既有正式查询服务；多数据集任务可切换栏目，按证券、日期等条件筛选，游标分页并展开完整记录。
- 日期和月份默认条件明确显示；金额 Decimal 以精确字符串传输，空值不填零。归档数据和盘中快照分开标识，空结果不等于完整性通过。
- 任务/视图/筛选字段采用后端白名单；查询取消、任务切换和过期结果沿用公共查询作用域。
- 原设计预览 work/desktop-redesign-react 与原客户端保留；本轮不改采集器、数据库结构、业务存储契约或保存配置。

## 验证

- tests/test_desktop_preview.py 与 tests/test_desktop_bridge.py：13 项通过，覆盖实际登记服务签名、越权视图与字段拒绝、金额精度及游标。
- scripts/build_desktop_launcher.py 使用共享构建锁完成 TypeScript/Vite、协议及启动参数检查，重建 dist/EmpireDesktop/Empire.exe，保留程序配置。
- desktop/qa/live-preview.cjs 启动真实 Electron 与原 Runtime：79 个视图查询无错误，有后续游标的视图检查第二页；证券样本 000001.SZ、题材编号 1、日期 2026-10-28。检查任务内表格、记录详情及返回运行卡片。
- 查询结果摘要：desktop/qa-output/live-preview.json；截图：desktop/qa-output/task-data-preview.png（本机忽略提交）。
- 这是查询路径与界面验收，部分视图当前无数据，不代表全市场或历史数据完整性验收。预览请求不启动采集、不写业务；真实 Runtime 启动仍会恢复用户已保存计划。

## 交付边界

交付本机双击启动器，依赖仓库 Electron 和 Python 环境；未将其称为独立可搬移安装包或完整正式发布门禁通过。
