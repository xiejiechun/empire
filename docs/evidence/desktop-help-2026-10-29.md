# 新版客户端说明接入（2026-10-29）

目标：将新版问号的一句提示替换为可阅读、可检索的离线说明，补齐新版操作指南。

开工已有大量业务与文档未提交修改；同目录另一聊天正在修复通达信和远航采集。未改其业务代码、配置或数据库，未关闭真实客户端。本轮无错误修复 ID 或错误清理。

## 实现

- `desktop/src/Help.tsx`、`help.css`：独立阅读组件；App 顶栏、问号和功能搜索进入同一抽屉。
- 构建时直接读取统一 `storage_reference.md`，156 篇说明；不增加后端 API 或第二份数据字典。新增 react-markdown / remark-gfm，锁文件已更新；不渲染原始 HTML，不执行外部链接。
- 新版权威指南 `src/empire/documentation/topics/desktop-client.md` 登记到 help-index 并重新生成聚合物。指南说明入口、保存、生效、恢复、记录、限制与排错；共享旧文显示新版导航提示。
- 全文多词搜索、分类目录、章节跳转、help 关联链接及最近 50 项返回历史。技术与数据库分类默认折叠。
- 同步 desktop README、根 README 和实现状态。

## 验证与边界

- `npm.cmd --prefix desktop run build`：TypeScript 与 Vite 构建通过；现有大包警告仍存在。
- `node desktop/qa/help.cjs`：隔离 Electron 通过指南、搜索、数据库文章、返回、help 链接、无结果及窄屏检查；截图为 `desktop/qa-output/help-wide.png`、`help-narrow.png`。模拟后端不等于真实部署验收。
- `scripts/documentation_build.py check`：156 篇聚合一致通过。
- 显式 `documentation_contract.py review` 已尝试，但被同时进行的通达信源码变化拦截：六项 tdx 任务及 mysql:shareholder_change 配套正文未更新；未通过无关正文或豁免刷新审阅。
- 未运行正式发布或重启真实客户端，以免干扰同环境修复。前端构建已产出；本机启动器下次正常启动读取新资源。未宣称独立安装包或全仓门禁完成。

本次不涉及采集器或数据库设计变更，实采与迁移不适用。全仓审阅及联合发布须在并发修复完成、源输入稳定后执行。

## 后续用户要求：按当前客户端精简

用户指出完整目录过于复杂，要求按实际功能重构。新版现仅展示五篇：快速开始、采集与计划、查看结果、连接与资源、常见问题。正文直接对应当前页面动作；移除旧导航对照、数据库与开发维护内容。技术资料保留于仓库和原聚合物，不进入新版搜索；来源范围与限制保留于任务“采集说明”。五篇权威片段直接由前端导入，没有复制正文。

本轮验证：TypeScript/Vite 构建通过；隔离 Electron 核对五篇均可打开、全文搜索、返回、关联链接、无结果及技术文章不可搜到；宽窄截图已人工查看（窄屏等待抽屉尺寸动画结束后截图）。`documentation_contract.py review` 和 `verify_documentation.py` 均通过（472 documents、3658 links、59 schema tables）。前端主资源从约 1834 kB 降为 1294 kB，仍有构建体积警告。

本轮未操作生产配置、任务或数据库，未重启实际客户端；已构建前端将在本机客户端下次正常启动时加载。本轮证据为隔离阅读验收，未执行完整独立安装包发布门禁。
