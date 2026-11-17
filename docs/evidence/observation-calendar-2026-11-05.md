# 多指标观察日历实施与验证

## 实现范围

用户要求参考图片新增多指标观察日历。已实现独立顶栏与功能搜索入口、已有指数目录及常用指数快捷选择、月份切换、四种两融市场口径、11项指标搜索/分类/增删/排序、三种密度、逐指标大于等于阈值高亮、本机视图保存及当月CSV原值导出。

新增 observation_calendar 只读业务插件和页面登记，复用正式日历、指数行情、市场两融查询。桌面桥仅做固定操作分派与日期/精确数值序列化；没有新SQL写入、结构迁移、Redis键、采集任务或业务副本。日历缺失、行情缺失、真实零值、休市与未来分别保留。最早支持1991-01，额外读取的前收窗口从正式日历起点1990-12-19开始。

已有共享工作区改动保留；本次没有提交或推送其他任务的变更，没有清理错误记录、队列或业务数据。来源采集及5%实采不适用：没有开发或修改采集器。

## 验证证据

- 35项专项与调用链测试通过：test_observation_calendar、test_desktop_bridge、test_assembly_contract、test_market_review。包含跨年/闰月网格、日历缺口、缺前收、零分母、未来、精度、截断拒绝、服务失败和桥接序列化。
- TypeScript检查及本次Python Ruff通过；精确装配与启动顺序检查通过。新增插件不会导入QtWidgets。
- Electron隔离交互验证通过：选择排序、高亮、保存后重新进入、CSV精确金额、切月旧响应竞争、失败清除旧结果、重试、760像素宽度横向滚动、月份滚轮不改值。脚本 desktop/qa/observation.cjs，独立构建 build/observation-ui；宽窄截图位于 desktop/qa-output/observation-wide.png 和 observation-narrow.png（测试数据）。
- 真实只读核对脚本 scripts/verify_observation_calendar.py：未启动Runtime、采集或归档器。2026-10查询上证指数1A0001、沪深京合计，573项正式指数目录，35个网格日期，11项指标各有17个当月交易日，日历缺日0；收盘原值逐日与原正式查询一致。1991-01指数收盘/涨跌幅/量额22日，两融为缺值，日历缺日0。结果见 build/observation-live.json 与 observation-live-earliest.json。
- 本机启动器官方构建入口成功，前端构建与传输测试包含在入口内，原程序目录配置保留；报告 build/desktop-launcher/0a1a52a3dce5461c8c4bc37357641ef0/report.json。仅证明依赖仓库的本机启动器，不是独立分发验收。
- 使用Windows computer-use检查正式EXE打开的Electron可见窗口，实际进入观察日历，默认上证指数、当月月份、常用指数快捷项与4项默认指标正常；2026-10-26至11-04真实值、正式休市日、当天缺值和未来提示已观察。最终边界修正后正常关闭并重新构建，从项目外临时工作目录启动，配置保持一致，正式窗口已连接并重新打开当月日历。Runtime正常启动会恢复已有计划，不能称整次启动绝无业务写入。

## 尚未通过的共享门禁

全局 documentation_contract.py review 已执行但拒绝：其他在途修改涉及 ths-market-margin、三张财报表、指数目录/行情/年度证明、资本运作表和 collection-control 的源码变动而对应审阅尚未完成。本次未使用无依据的 unchanged 豁免，也没有覆盖他人审阅记录。权威观察日历与查看结果正文已更新，聚合180主题生成及只读检查通过；verify_documentation.py 因上述全局审阅过期失败。

架构全局检查仍有其他任务新增的 index_prices.downloads、index_prices.planning、industries.staging、plugins.collectors.ths_maintenance 未分类；本次新增业务归属已登记，无新增跨层导入债务。test_headless_pages 的旧固定任务数52断言失败（当前53项）；实际QtWidgets导入为false，另外两项通过。本次没有改写无关任务数或给其他业务登记未经审阅的归属。

因此不声称完整发布门禁或全量测试通过。汇率、北向资金、成分股占比与自定义公式未接入；市场两融与指数行情各有范围，非原子跨数据集快照，不支持严格历史版本信号回放。
