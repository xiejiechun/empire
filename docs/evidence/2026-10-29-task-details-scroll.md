# 2026-10-29 采集任务详情滚动修复

- 问题入口：采集管理 → 采集任务 → 股票回购（东方财富）→ 运行与记录 → 更多运行信息；详情底部被裁切，无可用滚动区域。界面问题，无错误记录 ID，无 Redis 清理。
- 原因：Ant Design 6.6.8 使用 ant-tabs-body-holder，旧样式仍指向 ant-tabs-content-holder，滚动规则未命中。
- 修复：使用当前组件容器作为独立滚动区域，明确 flex 和最小高度；保留任务标题、操作区、标签栏和左侧目录。无业务、存储、任务策略变更。
- 回归：node desktop/qa/task-details-scroll.cjs；真实组件渲染 60 条运行信息，1366×768、1920×1080、3440×1369 下滚轮均到达最后字段，标题/目录位置不变，无页面水平溢出。
- 构建：npm.cmd --prefix desktop run build 通过；scripts/build_desktop_launcher.py 通过（含 transport 测试），保留程序目录配置。
- 真实桌面：只读打开既有股票回购任务，1366×768 下展开详情，滚动区高度 402、内容高度 1456、scrollTop 1053，确认到底。截图 desktop/qa-output/task-details-scroll-live.png。未手动启动采集或修改配置。
- 已正常关闭旧窗口，构建后从 C:/Windows 工作目录启动 dist/EmpireDesktop/Empire.exe，恢复桌面。
- 正式门禁：scripts/release.py 的环境、依赖、帮助和文档检查通过；数据库设计检查因已有 dividends.unit 容量证据过期而失败，涉及 src/empire/features/capital_actions/dividend_discovery.py。记录 build/releases/0f1402a380a14232af2fb8cc67e71d58。此次本地客户端更新不宣称完整发布门禁通过。
