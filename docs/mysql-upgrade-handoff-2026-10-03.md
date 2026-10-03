# MySQL 升级阶段交接（2026-10-03）

> 后续状态：用户已授权补齐完整方案，现已完成部署和最终验收。见 [最终报告](mysql-upgrade-final-2026-10-03.md)。以下保留当时的阶段交接/审阅记录。

## 状态与交付边界

**实施中，整套方案未完成，不能交付真实库迁移或正式验收。** 本记录只描述已完成的状态访问优化和只读预检，不能替代 [实施方案](mysql-upgrade-implementation-plan-2026-10-03.md) 的完成清单。

真实业务库未执行 DDL、业务 DML 或缓存失效；未替换 EXE。原桌面窗口保持运行，没有启动第二个面向真实库的归档器。数据库服务及生产者代理目录没有改动。

## 本阶段已实现

| 方案项目 | 本阶段结果 |
| --- | --- |
| 工作区及环境基线 | 保存任务开始前 474 个源码/脚本/文档文件摘要、Git HEAD/dirty 清单；已有改动未提交或丢弃。根配置与程序配置的 MySQL host/port/database/user 相同。未输出密码。其他同项目聊天检查时均非 active |
| 统一证券身份入口 | contracts/security.py 使用既有六位代码.市场；合法市场 SH/SZ/BJ，保留前导零；新浪股票规范化已调用。测试同代码不同市场、北交所旧代码不自动合并及非法格式。其他插件和物理 SQL 键尚未整体迁移 |
| 财报及资本状态局部访问 | FinancialDataset/CapitalDataset 声明 state_unit；公共归档在原事务内锁项目行，只读取当前单位、版本、进度和 manifest，JSON_SET 只提交变化路径，保留其他单位。完整审计仍读原状态集合。相同状态不写；新项目仍一行 |
| 完成等待 | SQL 回源只投影 progress；仍通过原 Stream 残留核对判断整轮完成，无逐批等待改动 |
| 显式总维护入口 | scripts/migrate_business_schema.py 当前只实现只读 preflight：精确限定 15 张现有 Empire 表，保存 DDL/索引、检查固定来源、读取状态大小和观察时的队列长度。额外来源拒绝并报告数量。report 明确 migration_ready=false |
| 状态专项及原归档回归 | 独立 MySQL 实例状态/来源预检 5 项；三张财报和分红/增发/配股端到端 87 项通过。使用原采集/入队/归档/查询测试，未以假插件替代 |

局部状态入口保留原 read_state 的来源核对语义和 save_state 的 dataset 元数据写法。既有显式维护脚本与归档器对 dataset 字段的命名存在差异，本阶段没有把新的命名校验作为隐式格式迁移；整体规范化必须在结构迁移阶段统一处理。

## 实际只读核查

项目配置目标为本机 3307 的 empire，MySQL 8.4.9。preflight 已确认十二张拟固定来源表的实际 DISTINCT source 与实施方案匹配，包括 kaipanla 和 cninfo。finance_news、collection_state、app_setting 未套用固定来源删除规则。未读取或修改 router_* 正文。

第一次逐表来源计数在 cashflow_statement 超过现有 20 秒读超时，因此该尝试不是完整基线。正式预检改用来源前缀 DISTINCT 查询，仅对额外来源计数；不得把它报告为逐表精确业务数量、内容集合或覆盖证明核验。运行中观察的 Stream 长度也不能作为停写迁移准入。

完整报告位于 build/mysql-upgrade-20261003/preflight.json；状态大小来自 JSON_STORAGE_SIZE，并非整个数据库实际磁盘占用。本次没有生产性能压测或 buffer pool 重置。

## 验证与性能证据

独立实例使用既有 E:/mysql/empire/server/bin/mysqld.exe，独立 datadir 位于 build/mysql-upgrade-20261003/mysql-drill/data，监听 127.0.0.1:13317。没有重启或修改 3307 服务。测试新建随机 _upgrade_drill 数据库，结束后只删除自身数据库；Redis 测试沿用精确随机 empire:test: 命名空间清理，未清共享库。

状态专项验证包括：其他证券及 manifest 保留、两个连接并发更新、事务失败回滚、首次状态插入、缺失 units 对象创建、空集合、来源拒绝、来源预检无 DDL/DML及 router 表不访问。声明与单位路径参数化；非法 JSON 路径身份拒绝。

15,000 单位、每单位 12 个报告期的合成状态中，同实例和连接池按完整读取、单元读取分别 5 次：

| 测量 | 完整读取 | 单元读取 |
| --- | --- | --- |
| 解码结果 JSON 字节数 | 4,740,126 | 442 |
| 五次耗时中位数 | 0.201880 秒 | 0.002085 秒 |

一次局部更新的三次 SQL 参数序列化大小为 176、49、335 字节。完整样本耗时、Python traced allocation 峰值及参数大小见 build/mysql-upgrade-20261003/state-performance.json。解码 JSON 长度不是网络报文计数，Python tracemalloc 不是进程总内存；这是合成状态的热读取比较，未测冷盘、索引体积或物理磁盘写入收益，也不是正式页面提速倍数。

87 项端到端回归覆盖相同业务零 DML、有效修订、旧响应、冷热摘要、提交后重放和清队、非季末报告期、缺字段修复及资本来源可用性规则。初次回归暴露维护脚本 dataset 元数据差异，新代码恢复原语义后完整重跑通过；失败测试的精确私有数据库/Redis命名空间已清理。此为测试缺陷处理，不涉及生产错误记录清除。

复核命令（项目根目录）：

```powershell
.\.venv\Scripts\python.exe scripts/migrate_business_schema.py preflight
.\.venv\Scripts\python.exe scripts/verify_mysql_upgrade_state.py --settings <独立实例设置JSON> --output <本次证据目录>
$env:EMPIRE_UPGRADE_DRILL='1'
$env:EMPIRE_UPGRADE_MYSQL_SETTINGS='<独立实例设置JSON绝对路径>'
.\.venv\Scripts\python.exe -m pytest tests/integration/test_state_unit_isolated.py -q --basetemp=<独立临时目录>
```

专项工具拒绝项目配置同 host/port 的 MySQL。测试实例设置文件不得带真实生产凭据提交；本次独立 root 账号空密码仅用于绑定回环地址的临时实例。

## 未完成项（全部仍为必需工作）

1. 固定来源登记、启动检查、归档错误来源拒绝、查询绑定使用同一权威声明；所有物理 source 删除与调用迁移。当前 business_schema 声明只供预检使用，尚未构成运行时保障。
2. 所有证券业务表转换 unified_code，逐调用点核验 source_symbol/node，历史证券 LEFT JOIN 和用户排序保持。
3. suspension_source_date 正式表、完整事件键、source_dates_known、原子并集归档、分页去重查询及旧 JSON 路径退役。
4. 正式页面过滤、稳定排序、有界键查询和索引改造，以及所有适用查询的前后 EXPLAIN/五次耗时/读行数/索引体积证据。
5. 显式 migrate/verify/status/resume/rollback 子命令、磁盘预算和本机恢复副本、全量流式业务键/内容/版本/来源日期/覆盖摘要、影子表原子切换、阶段日志及失败恢复/回退演练。当前入口没有任何迁移能力。
6. 旧维护入口逐一更新或退役、dataset 元数据命名统一、摘要/规范版本与覆盖证明转换依据。
7. 股票、新闻、日历、行业、分时、停复牌等适用矩阵完整验证和真实桌面验证。本阶段没有修改或验收这些物理结构。
8. 最终实施版文档、精确可追踪提交、独立审阅、正式发布门禁及真实库迁移验收。状态优化回归不能替代上述步骤。

## 文档和包状态

同步程序内财报存储主题、架构、去重、恢复、财报/资本来源说明及实现状态。页面登记没有变化，documentation-coverage.json 沿用现有主题关联。最终审阅/文档契约及全非集成回归结果记录在阶段证据。没有执行 verify-release.ps1 或打包，因为当前整套数据库升级实现尚未达到发布边界。

生产未迁移，当前记录不构成“已完成实施”的通知。独立审阅后最终验收阶段的部署边界仍按原方案执行。
