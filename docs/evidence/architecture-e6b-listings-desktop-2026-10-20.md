# E6b-listings 同包真实桌面验收

2026-10-20约11:13～11:43，使用 computer-use 技能的 `@oai/sky` 观察并操作正式 `dist/Empire/Empire.exe`，发布 `a2382f717972436d83956faefdfebda6`，干净构建 `fec74bcd50ffe00eaab19700d8c4c0d99b43dade`。运行状态实际显示该提交，Redis/MySQL/归档启用。原始带时间观察为本机 `build/architecture-e6b-listings-20261020/desktop-checkpoint.json`；工具会话截图为真实可见窗口，不以离屏结果代替。初始窗口3869236，1322×892。

## U1：独立生命周期

插件管理单停 `ui.listings`，查询及采集仍启用，随后恢复UI。直接停查询被拒绝：`Stop dependent plugins first: collector.ths_listings`。单停采集器后，查询和UI仍启用；原 `ths-listings` 任务点击立即采集，明确返回“该采集插件当前未启用，请先在插件管理中启用”，没有启动来源请求，原完成状态保持。随后恢复采集器，三行均显示启用；没有级联停用。

## U2：业务页面、草稿与可读性

从工作台进入数据目录，搜索“上市”打开“上市与发行资料”。首页200条，首条600601.SH/1990-12-19；下一页200条，首条000561.SZ。来源暂无84、缺上市日3的真实状态提示保留；不把提示转为有效资料。

股票候选603107选中上海汽配，实际详情上市2023-11-01、发行价14.2300；历史沿革长正文加载并滚至2017/2020段，滚动位置481。输入未应用000032草稿，切系统页再返回，草稿仍在，结果仍603107、历史标签及滚动位置保持；点击查询后才应用000032。000032.SZ上市1993-10-28、成立1993-12-04均原样显示，简介和历史标签保留日期冲突警告，未推算修补。

采集任务原状态已完成5580/5580、整轮已归档，每日18:00及原next_due保持；任务所示来源暂无83是其原运行事实，与当前页面84、私有41只实采为不同范围/时间，不强求相等。配置时间框滚轮仍18:00；重试次数原2，键盘Up生成未保存3，滚轮保持3，轮询/切页返回仍3；撤销后恢复2，保存按钮禁用。未保存日常策略或修改代理设置。

通过系统窗口大小操作将真实窗口缩为905×892，上市页实际转上下布局，证券/名称/日期完整、按钮可访问。再次查603107，长正文换行可读并实际滚动到349。内置帮助搜索“上市”，显示浏览/候选、七日全池回查、每日18:00、已保存设置优先；实际滚动读到日期字段及来源限制，未知不补造、失败保留位置、暂无/缺日不等于准备通过。

一次旧索引点击失效、一次不可见查询行未选中，均fresh观察后恢复，未据尝试宣称成功，也未误停其他插件。

## U3：同包查询、配置及正常关开

两次机器核验均exit0：`.venv/Scripts/python.exe build/architecture-e6b-listings-20261020/check_published_runtime.py --run a2382f717972436d83956faefdfebda6 --report build/architecture-e6b-listings-20261020/post-release.json`，关闭后output改 `post-release-closed.json`。核对包内清单、EXE及安装树；同一正式EXE从 `C:/Windows` 运行doctor，Redis/MySQL真实连接。冻结当前源码的正式API用安装配置查询列表前两页、代表和固定详情、补缺规划，与独立只读SQL精确比较；源码API不是EXE业务CLI，实际EXE查询另见上述页面观察。机器报告保留 `actual_desktop=pending_separate_real_observations`，未回写历史字段。

关闭前工作台45任务/活动0/既有失败5/pending0。Alt+F4后可见“正在保存进度、结束归档并关闭连接”，随后fresh枚举无Empire。执行 `close_desktop_settings.py` exit0：两config原字节保持，全部48行app_setting的payload和updated_at完全一致。偏好仅为启停造成的完整enabled registry展开及旧scheduler键退役，经严格审计、备份后恢复原字节，未知变更会拒绝；摘要见[设置核验](architecture-e6b-listings-settings-2026-10-20.json)。

随后重开同一正式EXE，11:43 fresh观察窗口3280246，1322×892工作台可见，本地服务已连接，45/0/5/0，日常新闻继续正常归档。数值为时间快照。最终只读资源核验exit0，13348实际UUID/datadir不变，仅四系统库、无他人客户会话；冻结工具和安装EXE匹配。未重启生产MySQL或共享Redis、未清业务及未解决错误。本批仅上市资料组织迁移验收，status/aliases及后续批次未由此完成。
