# 采集业务结构与升级

## 日常操作与结果

从“数据浏览”按市场或证券代码查询，入口与筛选方式保持不变。SQL 统一证券键为 unified_code（如 000001.SZ），程序解析出市场、六位代码及股票来源符号。固定来源由数据集登记校验，不允许把其他来源写进同一表；新闻仍按来源和新闻 ID 保存。当前股票目录退出的证券不会连带删除历史财报、事件和分时，缺当前名称时查询保留代码。

停复牌日历使用来源实际出现日期，生效时间另存。suspension_source_date 以来源日期及事件完整键关联；跨日期筛选先按来源日期索引取得完整事件键并去重，再关联事件；同一事件只返回一次。source_dates_known 为假或缺关系的记录不能通过数据准备，不能推断为当天无记录。消息中的 source_dates 保持原规范集合，不长期保存成功 HTTP 原文。

财报、分红、增发、配股的项目状态仍各一行 collection_state；归档只投影当前证券和公共进度，并局部更新 JSON。完整审计仍核验完整集合。JSON 扩容不保证物理写入始终减少；这是减少整项目传输和 Python 序列化的改造。

## 显式升级与生效

新空库使用现行 init-db。旧版完整业务库使用 scripts/migrate_business_schema.py；被替代的财报、行业、资本事件和分时单表创建脚本已退役。早于本轮输入契约的旧业务身份修复仍由标记为历史用途的显式入口处理，不能直接用本轮迁移跳过前置契约。

先正常关闭 Empire，等待任务和连接退出、待归档 Stream 清零。不能清队、删除锁或强杀数据库来满足条件。程序目录 config.toml 始终保留。

```powershell
.\.venv\Scripts\python.exe scripts/migrate_business_schema.py preflight
.\.venv\Scripts\python.exe scripts/migrate_business_schema.py migrate
.\.venv\Scripts\python.exe scripts/migrate_business_schema.py verify
```

命令默认根目录 config.toml，--config 显式覆盖。日志默认 build/mysql-upgrade-final/migration.json，--journal 可指定绝对路径。preflight 仅作只读观察；migrate 获取单实例和维护锁、检查空间及队列，逐表复制、流式核对规范内容和业务键后进行多表原子切换。MySQL DDL 会隐式提交，不能把这描述成一个可回滚的 SQL 事务。

配套新程序正常打开后生效；启动只检查结构，旧库会明确拒绝，不会自动迁移。Redis 摘要的业务身份和规范内容不因 SQL 列布局改变而改变，迁移逐表证明等价后保留。来源、规范版本发生变化则需要专项失效/重建，不能复用本次结论。

## 失败恢复与限制

status 查看阶段，resume 持同一日志续跑。日志绑定数据库 server_uuid/端口/库名、目标定义摘要及实际列/索引/约束 DDL；目标或结构改变拒绝续跑。复制失败只能重建本日志登记的影子表，旧正式表保留。切换后 verify 不一致时保持停机。

旧表保留为 empire_v1_* 本机恢复副本，不是程序双写路径。rollback 在停机且新正式表内容仍与迁移基线相等时核对旧副本后原子恢复；有新增或修订，即使行数相同也拒绝。恢复业务写入后采用前向修复或另行保全增量，不回退快照丢弃数据。维护副本在最终验收前不清理，后续清理须指定确切表集合。

本轮不合并历史换码身份、不生成公告日期、不提供历史财报版本回放、不拆分钟明细。数据库结构通过验收不等于全市场历史数据全部采集完成。

## 结构与验证参考

固定来源：股票 sina；行业和三表 ths；分红/增发/配股/停复牌 tdx；分时 kaipanla；日历 cninfo。权威登记见 contracts/business_schema.py。未知来源在入队规范化及 SQL 写入前拒绝。新闻和 collection_state 继续保留行级 source。

主键：股票 unified_code；行业 industry_code；成分 industry_code + unified_code；财报 unified_code + report_date；分时 unified_code + trade_date；资本事件 record_key；停复牌 unified_code + suspended_at + resume_key + record_key；来源日期在完整事件键前加 source_date；日历 trade_date。事件和财报日期索引包含市场表达式以保持原市场/代码排序。

集成测试按独立临时数据库隔离，不能再用伪造 source 清理共享业务；SQL 执行前还会核对当前测试拥有的数据库，拒绝遗漏的旧配置或导入别名访问其他库。迁移前要求股票业务条数与已发布状态一致，空业务表不能凭旧完成证明通过。迁移测试覆盖中断续跑、原子切换、回退、同条数内容变化拒绝及额外来源拒绝；来源专项覆盖原始响应到正式查询、冷热摘要、旧版本和提交后重放。最终实采范围与部署证据另记，不把模拟结果写成真实部署。
