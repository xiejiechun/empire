<!-- topic:技术参考|行业存储与完整性 -->
<!-- summary:核对行业存储与完整性的正式字段、规则和维护边界。 -->
# 行业存储与完整性

## 复盘只读汇总

公开 verify_current_snapshot 复用行业归档契约2的规范校验及摘要算法。每日复盘只读当前目录、当前成员和当前配置namespace下ths-industries的collection_state，检查来源ths、契约、数量、完整集合摘要及有效观测版本；同条数换成员或更名未同步证明时不返回板块金额。完整资金日榜通过后，按unified_code关联所选日main_flow。行业最多500、成员最多15000，每次SQL上限8秒；不写历史行业快照或汇总表，不修改采集和归档路径。历史页固定标注“按当前成分股回看”，部分覆盖仅合计已有数据。

## 字段与维护

正式实现归features/industries，bundle保留原插件、任务、页面和顺序。开发验证使用verify_indices.py的私有UUID资源生命周期，比较完整来源/入队/SQL/正式分页集合，失败与清理未完成均不通过；不更改用户保存的网络和任务策略。

字段、业务身份与当前集合保留规则见 [MySQL industry](help:MySQL%20industry)、[MySQL industry_member](help:MySQL%20industry_member)；SQL/Redis 失败保留原消息，公共归档器成功清队。

结构新增通过 scripts/migrate_business_schema.py 显式执行，维护前正常关闭程序并核对队列及已有业务数据；启动不自动建表。命令行 collect-industries 使用相同任务和归档路径。程序连接仍取程序目录 config.toml。

完整响应必须明确没有剩余分页；若采集提示“同花顺要求登录”，表示来源未提供数据，本轮不发布、不更新数据准备成功状态。当前完整性证明为契约 2，旧分页规则的状态及摘要不能代替新规则验收；重新采集后重建证明。命令行 collect-industries 启动该任务所需插件并执行一轮。
